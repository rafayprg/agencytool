"""Autopilot agent: watches the folder your downloader fills and feeds every finished
video through the whole agent chain, 24/7, with its own fixed settings (no review pause).

- A file is taken only when it is finished: same size on two scans and older than min_age_sec.
- Partial downloads (.part, .ytdl, .tmp …) are ignored.
- The original file is copied, never moved or deleted.
- data/autopilot_ledger.json remembers every file it took, so nothing is made twice.
- Only `max_queue` autopilot projects wait/run at once; the rest are picked up as those finish.
"""
import json
import logging
import re
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import library, notify, siblings
from .config import DATA, JOBS, LANGUAGES, VIDEO_EXTS
from .ingest import sidecar_info
from .job import Job, all_jobs

log = logging.getLogger(__name__)
CONFIG_FILE = DATA / "autopilot.json"
LEDGER_FILE = DATA / "autopilot_ledger.json"
SCAN_SEC = 30
PARTIAL_RE = re.compile(r"\.(part|ytdl|tmp|temp|crdownload|download)$|\.part-Frag|\.f\d+\.\w+$", re.IGNORECASE)
ACTIVE = ("queued", "running", "waiting")
RATE_RE = re.compile(r"^[+-][0-9]{1,2}%$")
MAX_AUTO_RETRIES = 3
RETRY_AFTER_SEC = 600  # failed projects (usually a network blip) are retried after 10 minutes

DEFAULTS = {
    "enabled": False,
    "watch_dir": "",
    "output_dir": "",          # optional: finished packages are copied here too
    "lang": "es",
    "voice": "es-MX-JorgeNeural",
    "rate": "+6%",
    "style": "neon-night",
    "formats": ["16x9", "9x16"],
    "max_queue": 2,
    "min_age_sec": 60,
    "include_subfolders": True,
    "extra_langs": [],         # also make every video in these languages (default voice each)
    "cleanup": True,           # delete working files once a video is done (keeps the finished package)
    "min_free_gb": 15,         # pause picking new videos when the disk gets this full
}


def _load(path: Path, default: dict) -> dict:
    try:
        return {**default, **json.loads(path.read_text(encoding="utf8"))}
    except (OSError, ValueError):
        return dict(default)


def _save(path: Path, data: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    tmp.replace(path)


def validate(cfg: dict, style_ids: set[str]) -> dict:
    """Clean a config coming from the UI. Raises ValueError with a readable message."""
    out = {**DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS}}
    watch = str(out["watch_dir"]).strip().strip('"')
    if watch and not Path(watch).is_dir():
        raise ValueError(f"watched folder does not exist: {watch}")
    output = str(out["output_dir"]).strip().strip('"')
    if output and not Path(output).is_dir():
        raise ValueError(f"output folder does not exist: {output}")
    if watch and output and Path(output).resolve() == Path(watch).resolve():
        raise ValueError("output folder must be different from the watched folder")
    if out["lang"] not in LANGUAGES:
        raise ValueError("unknown language")
    if str(out["voice"]).split("-")[0] != out["lang"]:
        raise ValueError("the voice does not match the language")
    if not RATE_RE.match(str(out["rate"])):
        raise ValueError("speed must look like +6% or -10%")
    if out["style"] not in style_ids:
        raise ValueError("unknown editing style")
    formats = [f for f in out["formats"] if f in ("16x9", "9x16")]
    if not formats:
        raise ValueError("pick at least one format")
    extra = [l for l in dict.fromkeys(out["extra_langs"] or []) if l != out["lang"]]
    if any(l not in LANGUAGES for l in extra):
        raise ValueError("unknown extra language")
    return {**out, "watch_dir": watch, "output_dir": output, "formats": formats,
            "max_queue": max(1, min(int(out["max_queue"]), 10)),
            "min_age_sec": max(10, min(int(out["min_age_sec"]), 3600)),
            "enabled": bool(out["enabled"]), "include_subfolders": bool(out["include_subfolders"]),
            "extra_langs": extra, "cleanup": bool(out["cleanup"]),
            "min_free_gb": max(1, min(int(out["min_free_gb"]), 2000))}


def file_key(path: Path, size: int, mtime: float) -> str:
    return f"{path.resolve()}|{size}|{int(mtime)}"


class Autopilot:
    def __init__(self, enqueue: Callable[[str], None]) -> None:
        self.enqueue = enqueue
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.sizes: dict[str, int] = {}   # path -> size seen on the previous scan
        self.state = {"last_scan": 0.0, "last_error": "", "waiting": 0, "seen": 0}
        self.thread = threading.Thread(target=self._loop, name="autopilot", daemon=True)

    # ---------- config ----------
    def config(self) -> dict:
        return _load(CONFIG_FILE, DEFAULTS)

    def save_config(self, cfg: dict) -> dict:
        with self.lock:
            _save(CONFIG_FILE, cfg)
        self.wake.set()
        return cfg

    def ledger(self) -> dict:
        return _load(LEDGER_FILE, {})

    def set_enabled(self, on: bool) -> dict:
        cfg = self.config()
        if on and not cfg["watch_dir"]:
            raise ValueError("set the watched folder first")
        if on and not Path(cfg["watch_dir"]).is_dir():
            raise ValueError(f"watched folder does not exist: {cfg['watch_dir']}")
        return self.save_config({**cfg, "enabled": on})

    # ---------- status ----------
    def status(self) -> dict:
        cfg = self.config()
        ledger = self.ledger()
        jobs = {j.id: j.data for j in all_jobs() if j.data.get("source", {}).get("autopilot")}
        counts = {"queued": 0, "running": 0, "done": 0, "error": 0, "review": 0, "cancelled": 0}
        for d in jobs.values():
            counts[d.get("status", "queued")] = counts.get(d.get("status", "queued"), 0) + 1
        recent = sorted(ledger.values(), key=lambda e: e["at"], reverse=True)[:40]
        durations = [d["finished"] - d["started"] for d in jobs.values()
                     if d.get("status") == "done" and d.get("finished") and d.get("started")]
        avg = sum(durations) / len(durations) if durations else 0
        today = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        remaining = self.state.get("pending_files", 0) + counts["queued"] + counts["running"]
        # real throughput: with the pipeline several videos overlap, so measure the gap between finishes
        finishes = sorted(d["finished"] for d in jobs.values() if d.get("status") == "done" and d.get("finished"))[-20:]
        per_video = (finishes[-1] - finishes[0]) / (len(finishes) - 1) if len(finishes) >= 3 else avg
        stats = {
            "avg_minutes": round(per_video / 60, 1),
            "done_today": sum(1 for d in jobs.values() if d.get("status") == "done" and d.get("finished", 0) >= today),
            "duplicates": sum(1 for e in ledger.values() if e.get("duplicate")),
            "remaining": remaining,
            "eta_hours": round(remaining * per_video / 3600, 1) if per_video else None,
            "per_day": round(86400 / per_video) if per_video else None,
        }
        rows = [{**e, "status": "duplicate" if e.get("duplicate") else jobs.get(e["job"], {}).get("status", "deleted"),
                 "stage": jobs.get(e["job"], {}).get("stage", ""),
                 "progress": jobs.get(e["job"], {}).get("progress", 0)} for e in recent]
        return {"config": cfg, "state": dict(self.state), "counts": counts, "stats": stats,
                "taken": sum(1 for e in ledger.values() if not e.get("duplicate")), "recent": rows}

    # ---------- scanning ----------
    def _candidates(self, cfg: dict) -> list[Path]:
        root = Path(cfg["watch_dir"])
        files = root.rglob("*") if cfg["include_subfolders"] else root.glob("*")
        out = []
        output = Path(cfg["output_dir"]).resolve() if cfg["output_dir"] else None
        for f in files:
            if not f.is_file() or f.name.startswith(".") or PARTIAL_RE.search(f.name):
                continue
            if f.suffix.lower() not in VIDEO_EXTS:
                continue
            if output and output in f.resolve().parents:
                continue
            out.append(f)
        return out

    def scan_once(self) -> int:
        """One pass: returns how many new projects were created."""
        cfg = self.config()
        self.state["last_scan"] = time.time()
        if not cfg["enabled"]:
            return 0
        root = Path(cfg["watch_dir"])
        if not root.is_dir():
            self.state["last_error"] = f"watched folder not found: {root}"
            return 0
        free_gb = shutil.disk_usage(JOBS.parent).free / 1024**3
        self.state["free_gb"] = round(free_gb, 1)
        if free_gb < cfg["min_free_gb"]:
            msg = f"paused: only {free_gb:.1f} GB free on the disk (limit {cfg['min_free_gb']} GB) — free some space"
            if self.state.get("last_error") != msg:
                notify.send(f"⚠️ Autopilot {msg}")
            self.state["last_error"] = msg
            return 0
        self.state["last_error"] = ""
        ledger = self.ledger()
        taken = {e["file"] for e in ledger.values()}
        now = time.time()
        ready: list[tuple[float, Path, int]] = []
        sizes: dict[str, int] = {}
        candidates = self._candidates(cfg)
        for f in candidates:
            try:
                st = f.stat()
            except OSError:
                continue
            key = file_key(f, st.st_size, st.st_mtime)
            if key in ledger:
                continue
            sizes[str(f)] = st.st_size
            stable = self.sizes.get(str(f)) == st.st_size and st.st_size > 0
            if stable and now - st.st_mtime >= cfg["min_age_sec"]:
                ready.append((st.st_mtime, f, st.st_size))
        self.sizes = sizes
        self.state["seen"] = len(candidates)
        self.state["pending_files"] = len(sizes)  # in the folder, not taken yet (incl. still downloading)
        self.state["waiting"] = len(ready)
        self._retry_failed(now)
        active = sum(1 for j in all_jobs() if j.data.get("source", {}).get("autopilot") and j.data.get("status") in ACTIVE)
        created = 0
        duplicates = 0
        for mtime, f, size in sorted(ready):
            if active >= cfg["max_queue"]:
                break
            key = file_key(f, size, mtime)
            fp = library.fingerprint(f, sidecar_info(f))
            jobs = self._create_all(cfg, f, fp)
            if not jobs:  # every language of this video is already made (or being made, maybe on the other PC)
                other = library.owner(library.key(fp, cfg["lang"])) or ""
                ledger[key] = {"file": str(f), "name": f.name, "job": other.split(" ")[0], "at": time.time(),
                               "duplicate": True, "where": other}
                _save(LEDGER_FILE, ledger)
                duplicates += 1
                continue
            ledger[key] = {"file": str(f), "name": f.name, "job": jobs[0].id, "at": time.time(), "re_take": str(f) in taken,
                           "langs": [j.data["options"]["lang"] for j in jobs]}
            _save(LEDGER_FILE, ledger)
            for job in jobs:
                self.enqueue(job.id)
            active += len(jobs)
            created += 1
        self.state["waiting"] = max(0, len(ready) - created - duplicates)
        self.state["pending_files"] = max(0, len(sizes) - created - duplicates)  # taken files are now counted as jobs
        return created

    def _retry_failed(self, now: float) -> None:
        """Unattended runs: give failed autopilot projects a few more tries (network blips)."""
        for job in all_jobs():
            d = job.data
            if not d.get("source", {}).get("autopilot") or d.get("status") != "error":
                continue
            if "already made" in d.get("error", ""):
                continue  # a duplicate is not a network blip
            tries = d.get("auto_retries", 0)
            if tries >= MAX_AUTO_RETRIES or now - d.get("updated", now) < RETRY_AFTER_SEC:
                continue
            job.set(status="queued", error="", auto_retries=tries + 1)
            job.log("Autopilot", f"retrying automatically ({tries + 1}/{MAX_AUTO_RETRIES})")
            self.enqueue(job.id)

    def _create_all(self, cfg: dict, f: Path, fp: str) -> list[Job]:
        """Main project (first language still missing) + language siblings for the rest; each language
        is claimed in the library first, so two PCs never make the same video in the same language."""
        langs = [cfg["lang"], *cfg["extra_langs"]]
        main: Job | None = None
        siblings_langs: list[str] = []
        for lang in langs:
            if library.owner(library.key(fp, lang)):
                continue
            if main is None:
                voice = cfg["voice"] if lang == cfg["lang"] else LANGUAGES[lang][1]
                options = {"lang": lang, "voice": voice, "rate": cfg["rate"], "style": cfg["style"],
                           "formats": cfg["formats"], "review": False, "crop": "", "export_dir": cfg["output_dir"],
                           "cleanup": cfg["cleanup"]}
                candidate = Job.create(options, {"kind": "watch", "input": str(f), "title": f.stem, "autopilot": True})
                if library.claim(library.key(fp, lang), candidate.id, f.name, str(f)):
                    shutil.rmtree(candidate.dir, ignore_errors=True)  # the other PC was faster
                    continue
                main = candidate
                main.log("Autopilot", f"picked up {f.name} from the watched folder")
            else:
                siblings_langs.append(lang)
        if main is None:
            return []
        made = [main]
        for sib in siblings.create(main, siblings_langs):
            if library.claim(library.key(fp, sib.data["options"]["lang"]), sib.id, f.name, str(f)):
                shutil.rmtree(sib.dir, ignore_errors=True)
                continue
            made.append(sib)
        log.info("autopilot: %s -> %s", f, ", ".join(j.id for j in made))
        return made

    def _loop(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception as exc:  # keep watching no matter what
                log.exception("autopilot scan failed")
                self.state["last_error"] = str(exc)[:300]
            self.wake.wait(SCAN_SEC)
            self.wake.clear()

    def start(self) -> None:
        self.thread.start()

    def nudge(self) -> None:
        """Scan soon (a project finished, settings changed)."""
        self.wake.set()
