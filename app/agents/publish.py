"""Stage 8: upload-ready package per language in jobs/<id>/publish/<lang>/:
videos, metadata.json (title, description with chapters, tags), captions.srt, UPLOAD.txt."""
import json
import re
import shutil
from pathlib import Path

from . import settings
from .config import JOBS
from .job import Job
from .voice import render_dir

CAPTION_WORDS = 7


def _ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3_600_000:02d}:{ms % 3_600_000 // 60_000:02d}:{ms % 60_000 // 1000:02d},{ms % 1000:03d}"


def chapters(timeline: dict) -> list[str]:
    fps, out, last = timeline["fps"], [], None
    for sc in timeline["scenes"]:
        label = sc["chapter"] + (f": {sc['callout']}" if sc.get("callout") else "")
        if sc["chapter"] != last:
            out.append(f"{_ts(sc['from'] / fps)} {label}")
            last = sc["chapter"]
    return out


def srt(timeline: dict) -> str:
    fps, blocks = timeline["fps"], []
    for sc in timeline["scenes"]:
        base = sc["from"] / fps
        words = sc["words"]
        for i in range(0, len(words), CAPTION_WORDS):
            chunk = words[i:i + CAPTION_WORDS]
            text = " ".join(w["w"] for w in chunk)
            blocks.append(f"{len(blocks) + 1}\n{_srt_time(base + chunk[0]['s'])} --> {_srt_time(base + chunk[-1]['e'])}\n{text}\n")
    return "\n".join(blocks)


BAD_CHARS = set('<>:"/|?*') | {chr(92)}


# heavy working files; the finished package in publish/ (and the output folder copy) stays
CLEANUP_PATHS = ["source/video.mp4", "source/upload.mp4", "analysis/phone.mp4", "analysis/audio_16k.wav",
                 "analysis/frames", "render/public", "render/final_16x9.mp4", "render/final_9x16.mp4"]


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0


def cleanup(job: Job, keep_publish_videos: bool = True) -> int:
    """Delete working files of a finished project. Language siblings that still need the
    download keep it: their files are hard links, so they are not affected."""
    pending = [s for s in job.data.get("siblings", [])
               if (JOBS / s / "job.json").exists() and "ingest" not in Job.load(s).data.get("done", [])]
    paths = [p for p in CLEANUP_PATHS if not (pending and p.startswith(("source/", "analysis/")))]
    if not keep_publish_videos:
        paths += ["publish/final_16x9.mp4", "publish/final_9x16.mp4"]
    freed = 0
    for rel in paths:
        target = job.dir / rel
        freed += _size(target)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    job.set(cleaned=True, exported_only=not keep_publish_videos)
    return freed


def _safe_name(title: str) -> str:
    """A Windows-safe folder name from a video title."""
    name = "".join(ch for ch in title if ch not in BAD_CHARS and ord(ch) >= 32).strip(" .")
    return (name or "video")[:80]


def run(job: Job) -> None:
    src_dir = render_dir(job)
    timeline = json.loads((src_dir / "timeline.json").read_text(encoding="utf8"))
    spec = json.loads(job.path("script", "scenes.json").read_text(encoding="utf8"))
    out = job.dir / "publish"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    videos = sorted(src_dir.glob("final_*.mp4"))
    for v in videos:
        shutil.copy2(v, out / v.name)
    for name in ("thumbnail.jpg", "original_thumbnail.jpg"):
        if (src_dir / name).exists():
            shutil.copy2(src_dir / name, out / name)
    intro = next((s["text"] for s in spec["scenes"]), "")
    hashtags = " ".join("#" + re.sub(r"\W", "", t) for t in spec.get("tags", [])[:3] if t.strip())
    description = "\n".join([intro, "", *chapters(timeline), "", hashtags])
    meta = {
        "title": spec["title"][:100],
        "description": description.strip(),
        "tags": spec.get("tags", []),
        "language": spec["lang"],
        "duration_sec": round(timeline["total"] / timeline["fps"], 1),
        "files": [v.name for v in videos],
        "source": job.data.get("source_url", ""),
    }
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf8")
    (out / "captions.srt").write_text(srt(timeline), encoding="utf8")
    upload = [
        "TITLE:", meta["title"], "",
        "DESCRIPTION:", meta["description"], "",
        "TAGS:", ", ".join(meta["tags"]), "",
        f"FILES: {', '.join(meta['files'])}  (+ captions.srt)",
        "THUMBNAIL: thumbnail.jpg (original: original_thumbnail.jpg)" if (out / "thumbnail.jpg").exists() else "THUMBNAIL: none",
    ]
    (out / "UPLOAD.txt").write_text("\n".join(upload) + "\n", encoding="utf8")
    export = job.data["options"].get("export_dir")
    if export:
        dest = Path(export) / f"{_safe_name(meta['title'])} ({job.id})"
        shutil.copytree(out, dest, dirs_exist_ok=True)
        job.log("Publisher", f"copied to {dest}")
    job.log("Publisher", f"upload package ready: {len(videos)} videos, captions, title, description, tags")
    exported = bool(export)
    if job.data["options"].get("cleanup") or (job.data["options"].get("cleanup") is None and settings.load()["cleanup_after_done"]):
        freed = cleanup(job, keep_publish_videos=not exported)
        job.log("Publisher", f"disk saver: removed {freed / 1024**2:.0f} MB of working files")
