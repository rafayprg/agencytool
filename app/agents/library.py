"""Library: the memory of every video the studio has taken, so the same video is never made
twice in the same language — on this PC, or on two PCs sharing one library folder.

Fingerprint = YouTube id when known ("yt:<id>", from the link or a yt-dlp .info.json),
otherwise a fast content hash ("sha1:…", size + first and last 2 MB).
The library key is "<fingerprint>|<language>": the same video may be made once per language.

Two PCs: point Settings → "Shared library folder" on both PCs at the same network folder.
Every claim takes a lock file there, so both can watch the same downloads folder safely.
"""
import hashlib
import json
import os
import re
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import settings
from .config import DATA, JOBS

HASH_CHUNK = 2 * 1024 * 1024
YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")
DEAD = ("error", "cancelled", "deleted")  # a video owned only by these may be made again
LOCK_STALE_SEC = 30
LOCK_WAIT_SEC = 20
PC = socket.gethostname()
LIBRARY_FILE: Path | None = None   # tests set this; otherwise taken from Settings
_lock = threading.RLock()


# ---------- fingerprints ----------
def youtube_id(url: str) -> str:
    m = YT_ID_RE.search(url or "")
    return m.group(1) if m else ""


def file_hash(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(HASH_CHUNK))
        if size > 2 * HASH_CHUNK:
            f.seek(-HASH_CHUNK, 2)
            h.update(f.read(HASH_CHUNK))
    return "sha1:" + h.hexdigest()


def fingerprint(path: Path | None = None, info: dict | None = None, url: str = "") -> str:
    info = info or {}
    vid = info.get("id") if str(info.get("extractor_key", "Youtube")).lower().startswith("youtube") else ""
    vid = vid or youtube_id(info.get("webpage_url", "")) or youtube_id(url)
    if vid:
        return f"yt:{vid}"
    if path is not None and path.exists():
        return file_hash(path)
    return ""


def key(fp: str, lang: str) -> str:
    return f"{fp}|{lang}" if fp else ""


# ---------- storage (local or shared folder) ----------
def library_file() -> Path:
    if LIBRARY_FILE is not None:
        return LIBRARY_FILE
    shared = settings.load()["library_dir"].strip()
    return (Path(shared) if shared else DATA) / "library.json"


@contextmanager
def _locked():
    """In-process lock + a lock file next to the library (works across PCs on a shared folder)."""
    with _lock:
        f = library_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        lock = f.with_suffix(".lock")
        deadline = time.time() + LOCK_WAIT_SEC
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{PC} {time.time()}".encode())
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > LOCK_STALE_SEC:
                        lock.unlink(missing_ok=True)  # left behind by a crashed PC
                        continue
                except OSError:
                    continue
                if time.time() > deadline:
                    raise RuntimeError(f"library is locked by another PC ({lock})")
                time.sleep(0.2)
        try:
            yield f
        finally:
            lock.unlink(missing_ok=True)


def _load(f: Path) -> dict:
    try:
        data = json.loads(f.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return {}
    return {k: _normalise(k, v) for k, v in data.items()}


def _normalise(k: str, e: dict) -> dict:
    """Older entries stored plain job ids; turn them into {id, pc, status}."""
    jobs = [j if isinstance(j, dict) else {"id": j, "pc": PC, "status": ""} for j in e.get("jobs", [])]
    return {**e, "jobs": jobs}


def _save(f: Path, data: dict) -> None:
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    tmp.replace(f)


def _local_status(job_id: str) -> str:
    f = JOBS / job_id / "job.json"
    if not f.exists():
        return "deleted"
    try:
        return json.loads(f.read_text(encoding="utf8")).get("status", "queued")
    except (OSError, ValueError):
        return "queued"


def _status(j: dict) -> str:
    """This PC's projects are checked live; another PC's projects use the status it reported."""
    return _local_status(j["id"]) if j.get("pc", PC) == PC else (j.get("status") or "queued")


def _owner_in(entry: dict | None, exclude_job: str) -> str | None:
    if not entry:
        return None
    for j in reversed(entry["jobs"]):
        if j["id"] != exclude_job and _status(j) not in DEAD:
            return j["id"] if j.get("pc", PC) == PC else f"{j['id']} on {j['pc']}"
    return None


# ---------- public API ----------
def owner(k: str, exclude_job: str = "") -> str | None:
    """The live project that already has this video in this language, if any."""
    if not k:
        return None
    with _lock:
        return _owner_in(_load(library_file()).get(k), exclude_job)


def claim(k: str, job_id: str, name: str, source: str) -> str | None:
    """Atomically: if nobody owns k, record job_id as its owner and return None; else return the owner."""
    if not k:
        return None
    with _locked() as f:
        data = _load(f)
        entry = data.get(k)
        other = _owner_in(entry, job_id)
        if other:
            return other
        entry = entry or {"first_seen": time.time(), "jobs": []}
        jobs = [j for j in entry["jobs"] if j["id"] != job_id] + [{"id": job_id, "pc": PC, "status": "queued"}]
        data[k] = {**entry, "name": name, "source": source, "jobs": jobs, "last": time.time()}
        _save(f, data)
    return None


def register(k: str, job_id: str, name: str, source: str) -> None:
    """Record without checking (backfill of old projects)."""
    if not k:
        return
    with _locked() as f:
        data = _load(f)
        entry = data.get(k, {"first_seen": time.time(), "jobs": []})
        jobs = [j for j in entry["jobs"] if j["id"] != job_id] + [{"id": job_id, "pc": PC, "status": _local_status(job_id)}]
        data[k] = {**entry, "name": name, "source": source, "jobs": jobs, "last": time.time()}
        _save(f, data)


def report_status(job_id: str, status: str) -> None:
    """Tell the (possibly shared) library how a project ended, so the other PC knows too."""
    try:
        with _locked() as f:
            data = _load(f)
            changed = False
            for e in data.values():
                for j in e["jobs"]:
                    if j["id"] == job_id and j.get("pc", PC) == PC and j.get("status") != status:
                        j["status"] = status
                        e["last"] = time.time()
                        changed = True
            if changed:
                _save(f, data)
    except (OSError, RuntimeError):
        pass  # the library being briefly unreachable must never fail a video


def entries() -> list[dict]:
    """Every remembered video+language with the status of its latest project (newest first)."""
    with _lock:
        data = _load(library_file())
    rows = []
    for k, e in data.items():
        fp, _, lang = k.partition("|")
        latest = e["jobs"][-1] if e["jobs"] else None
        rows.append({"fingerprint": fp, "lang": lang, "name": e.get("name", ""), "source": e.get("source", ""),
                     "job": latest["id"] if latest else "", "pc": latest.get("pc", PC) if latest else PC,
                     "status": _status(latest) if latest else "deleted",
                     "times": len(e["jobs"]), "first_seen": e.get("first_seen", 0), "last": e.get("last", 0)})
    return sorted(rows, key=lambda r: r["last"], reverse=True)


def backfill() -> int:
    """Remember projects made before the library existed, and move old keys to fp|lang."""
    added = 0
    with _locked() as f:
        data = _load(f)
        migrated = {}
        for k, e in data.items():
            if "|" in k:
                migrated[k] = e
                continue
            lang = "es"
            for j in e["jobs"]:
                jf = JOBS / j["id"] / "job.json"
                if jf.exists():
                    lang = json.loads(jf.read_text(encoding="utf8")).get("options", {}).get("lang", lang)
            migrated[key(k, lang)] = e
        if migrated != data:
            _save(f, migrated)
    for d in sorted(JOBS.iterdir()) if JOBS.exists() else []:
        jf = d / "job.json"
        if not jf.exists():
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        if data.get("fingerprint") or not data.get("video"):
            continue
        k = key(fingerprint(d / data["video"], url=data.get("source_url", "")), data.get("options", {}).get("lang", ""))
        if k and not owner(k):
            register(k, d.name, data.get("title", d.name), data.get("source_url") or data.get("source", {}).get("input", ""))
            added += 1
    return added
