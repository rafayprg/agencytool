"""Downloader agent: YouTube video / playlist / channel URL, public Google Drive
folder or uploaded file -> jobs/<id>/source/video.mp4 + metadata.

A playlist, channel or Drive folder becomes one job per video (bulk mode):
the first video stays in this job, the rest are returned as new jobs.
"""
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import JOBS, PYTHON, VIDEO_EXTS
from . import library
from .job import Job
from .media import FFMPEG, kill_tree, probe

YTDLP = [str(PYTHON), "-m", "yt_dlp", "--js-runtimes", "node", "--no-warnings", "--no-playlist"]
PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
FORMAT = ("bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][vcodec^=avc1]+ba/"
          "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b")  # H.264 first: fast to decode


def _run(args: list[str], what: str) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        raise RuntimeError(f"{what} failed: {' '.join(tail)[:500]}")
    return proc.stdout


def expand_url(url: str) -> list[str]:
    """Playlist / channel URL -> one URL per video; a single video stays as is."""
    out = _run([*YTDLP[:-1], "--flat-playlist", "-J", url], "reading the link")
    info = json.loads(out)
    entries = info.get("entries")
    if not entries:
        return [url]
    urls: list[str] = []
    for e in entries:
        if e.get("entries") or (e.get("_type") == "playlist" and e.get("url")):
            urls.extend(expand_url(e["url"]))
        elif e.get("id"):
            urls.append(e.get("url") or f"https://www.youtube.com/watch?v={e['id']}")
    return urls


def _download(job: Job, url: str, progress: Callable[[float], None]) -> None:
    src = job.path("source", "x").parent
    job.log("Downloader", f"downloading {url}")
    args = [*YTDLP, "-f", FORMAT, "--merge-output-format", "mp4", "--ffmpeg-location", FFMPEG,
            "--write-info-json", "--write-thumbnail", "--no-write-subs", "--newline",
            "-o", str(src / "video.%(ext)s"), url]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf8", errors="replace")
    try:
        tail = _follow(proc, progress)
        code = proc.wait()
    finally:
        if proc.poll() is None:
            kill_tree(proc)
    if code != 0 or not (src / "video.mp4").exists():
        raise RuntimeError("download failed: " + " ".join(tail)[:500])
    info = json.loads((src / "video.info.json").read_text(encoding="utf8"))
    _finish(job, src / "video.mp4", {
        "title": info.get("title") or job.id,
        "channel": info.get("channel") or info.get("uploader") or "",
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "language": info.get("language") or "",
        "source_url": url,
    })


def _follow(proc: subprocess.Popen, progress: Callable[[float], None]) -> list[str]:
    """Turn yt-dlp's per-stream percentages into one progress value. Returns the last lines."""
    tail: list[str] = []
    finished_streams = 0  # video stream (~85% of the bytes) first, then audio
    for line in proc.stdout:
        tail = [*tail, line.strip()][-4:]
        m = PCT_RE.search(line)
        if not m:
            continue
        pct = min(float(m.group(1)) / 100, 1.0)
        progress(pct * 0.85 if finished_streams == 0 else 0.85 + pct * 0.14)
        if pct >= 1:
            finished_streams += 1
    return tail


def _from_file(job: Job, path: Path, title: str, keep_source: bool = False, meta: dict | None = None) -> None:
    """Bring a local file into the job. keep_source=True (watched folder) never moves or deletes it."""
    dest = job.path("source", "video.mp4")
    if path.suffix.lower() == ".mp4":
        if path.resolve() != dest.resolve():
            (shutil.copy2 if keep_source else shutil.move)(str(path), dest)
    else:
        job.log("Downloader", f"converting {path.suffix} to mp4")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(path), "-c:v", "libx264", "-crf", "18",
                        "-preset", "fast", "-c:a", "aac", str(dest)], check=True)
        if not keep_source:
            path.unlink(missing_ok=True)
    base = {"title": title, "channel": "", "description": "", "tags": [], "language": "", "source_url": ""}
    _finish(job, dest, {**base, **{k: v for k, v in (meta or {}).items() if v}})


def sidecar_info(video: Path) -> dict:
    """Raw metadata a downloader saved next to the video (yt-dlp style <name>.info.json or <name>.json)."""
    for cand in (video.with_suffix(".info.json"), video.with_suffix(".json")):
        if not cand.exists():
            continue
        try:
            info = json.loads(cand.read_text(encoding="utf8"))
        except (ValueError, OSError):
            continue
        if isinstance(info, dict):
            return info
    return {}


def sidecar_meta(video: Path) -> dict:
    info = sidecar_info(video)
    if not info:
        return {}
    return {
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "language": info.get("language") or "",
        "source_url": info.get("webpage_url") or info.get("url") or "",
    }


def sidecar_thumbnail(video: Path) -> Path | None:
    """The original creator's thumbnail saved next to the video, if the downloader kept one."""
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        cand = video.with_suffix(ext)
        if cand.exists():
            return cand
    return None


class DuplicateVideo(RuntimeError):
    pass


def _claim(job: Job, fp: str, name: str) -> None:
    """Remember this video (per language); refuse it if another live project already made it."""
    k = library.key(fp, job.data["options"]["lang"])
    if not k:
        return
    if job.data["options"].get("allow_duplicate"):
        library.register(k, job.id, name, job.data["source"].get("input", ""))
    else:
        other = library.claim(k, job.id, name, job.data["source"].get("input", ""))
        if other:
            raise DuplicateVideo(f"already made in project {other} — open Library, or tick 'make it again' to redo it")
    job.set(fingerprint=fp)


# files a language sibling shares with its main project (hard links: no extra disk space)
SIBLING_FILES = ["source/video.mp4", "source/video.info.json", "source/video.webp", "source/video.jpg",
                 "source/video.png", "analysis/phone.mp4", "analysis/transcript.json", "analysis/full_frame.jpg",
                 "analysis/crop_preview.jpg", "script/scenes_src.json"]
SIBLING_FIELDS = ["video", "duration", "width", "height", "title", "channel", "description", "tags",
                  "language", "source_url", "crop", "fingerprint"]


class WaitForMain(Exception):
    """The main project has not transcribed the video yet — try again later."""


def _link_or_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def _from_main(job: Job) -> None:
    """Language sibling: reuse the main project's download, crop, transcript and scenes."""
    main_id = job.data["source"]["input"]
    main_dir = JOBS / main_id
    if not (main_dir / "job.json").exists():
        raise RuntimeError(f"main project {main_id} was deleted")
    main = Job.load(main_id)
    if not all(main.done(s) for s in ("ingest", "crop", "transcribe", "scenes")):
        if main.data.get("status") in ("error", "cancelled"):
            raise RuntimeError(f"main project {main_id} stopped before the transcript was ready — retry it first")
        raise WaitForMain(main_id)
    for rel in SIBLING_FILES:
        if (main_dir / rel).exists():
            _link_or_copy(main_dir / rel, job.dir / rel)
    if not (job.dir / "analysis" / "phone.mp4").exists():
        raise RuntimeError("the main project's files were already cleaned up — make this language from a fresh project")
    _claim(job, main.data.get("fingerprint", ""), main.data.get("title", ""))
    job.set(**{k: main.data[k] for k in SIBLING_FIELDS if k in main.data})
    for stage in ("crop", "transcribe", "scenes"):
        job.mark(stage)
    job.log("Downloader", f"reusing download, crop and transcript of {main.data.get('title', main_id)}")


def _finish(job: Job, video: Path, meta: dict) -> None:
    info = probe(video)
    if not info["width"]:
        raise RuntimeError("the file has no video stream")
    job.set(video=str(video.relative_to(job.dir)).replace("\\", "/"), duration=info["duration"],
            width=info["width"], height=info["height"], **meta)
    job.log("Downloader", f"ready: {meta['title']} ({info['width']}x{info['height']}, {info['duration']:.0f}s)")


def _drive(job: Job, url: str) -> list[Path]:
    import gdown

    inbox = job.path("source", "drive", "x").parent
    job.log("Downloader", "downloading Google Drive folder (must be shared: anyone with the link)")
    gdown.download_folder(url=url, output=str(inbox), quiet=True, remaining_ok=True)
    files = sorted(p for p in inbox.rglob("*") if p.suffix.lower() in VIDEO_EXTS)
    if not files:
        raise RuntimeError("no video files found in that Drive folder")
    return files


def run(job: Job, progress: Callable[[float], None]) -> list[Job]:
    """Returns extra jobs created for bulk inputs (the worker queues them)."""
    source = job.data["source"]
    kind, value = source["kind"], source["input"]
    extra: list[Job] = []
    # bulk inputs: the extra projects are created only after this project's own video is ready,
    # so a failed first download (and its retries) never leaves orphan or duplicate projects
    if kind == "url" and "drive.google.com" in value:
        files = _drive(job, value)
        _claim(job, library.fingerprint(files[0]), files[0].name)
        _from_file(job, files[0], files[0].stem)
        extra = [Job.create(job.data["options"], {"kind": "file", "input": str(f), "title": f.stem}) for f in files[1:]]
    elif kind == "url":
        urls = expand_url(value)
        _claim(job, library.fingerprint(url=urls[0]), urls[0])  # checked before downloading anything
        _download(job, urls[0], progress)
        if len(urls) > 1:
            lang = job.data["options"]["lang"]
            fresh = [u for u in urls[1:] if not library.owner(library.key(library.fingerprint(url=u), lang))]
            skipped = len(urls) - 1 - len(fresh)
            job.log("Downloader", f"bulk link: {len(urls)} videos — {len(fresh)} more projects created"
                    + (f", {skipped} already made (skipped)" if skipped else ""))
            extra = [Job.create(job.data["options"], {"kind": "url", "input": u}) for u in fresh]
    elif kind == "file":
        path = Path(value)
        _claim(job, library.fingerprint(path), path.name)
        _from_file(job, path, source.get("title") or path.stem)
    elif kind == "watch":
        path = Path(value)
        if not path.exists():
            raise RuntimeError(f"the file is gone from the watched folder: {path}")
        _claim(job, library.fingerprint(path, sidecar_info(path)), path.name)
        meta = sidecar_meta(path)
        _from_file(job, path, meta.get("title") or path.stem, keep_source=True, meta=meta)
        thumb = sidecar_thumbnail(path)
        if thumb:
            shutil.copy2(thumb, job.path("source", "video" + thumb.suffix.lower()))
    elif kind == "sibling":
        _from_main(job)
    else:
        raise RuntimeError(f"unknown source kind {kind}")
    return extra
