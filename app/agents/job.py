"""Job folder + persistent state (jobs/<id>/job.json). Thread-safe for one worker + API readers."""
import json
import re
import secrets
import threading
import time
from pathlib import Path

from .config import JOBS

JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,80}$")
MAX_LOG = 300
SAVE_RETRIES = 20
_lock = threading.RLock()


class JobDeleted(RuntimeError):
    pass


def _read(f: Path) -> dict:
    """Read job.json, retrying while Windows briefly locks it during a rename."""
    for attempt in range(SAVE_RETRIES):
        try:
            return json.loads(f.read_text(encoding="utf8"))
        except PermissionError:
            if attempt == SAVE_RETRIES - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError("unreachable")


def new_id() -> str:
    return time.strftime("j%Y%m%d-%H%M%S-") + secrets.token_hex(2)


def valid_id(job_id: str) -> bool:
    return bool(JOB_ID_RE.match(job_id)) and (JOBS / job_id / "job.json").exists()


class Job:
    def __init__(self, job_id: str, data: dict) -> None:
        self.id = job_id
        self.data = data

    @property
    def dir(self) -> Path:
        return JOBS / self.id

    def path(self, *parts: str) -> Path:
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save(self) -> None:
        """Atomic write. On Windows the rename fails while another process is reading
        job.json (antivirus, a second reader), so retry briefly before giving up."""
        with _lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / "job.json.tmp"
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf8")
            for attempt in range(SAVE_RETRIES):
                try:
                    tmp.replace(self.dir / "job.json")
                    return
                except PermissionError:
                    if attempt == SAVE_RETRIES - 1:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    def _fresh(self) -> dict:
        """Latest saved state: the API thread and the worker each hold their own Job object,
        so every update merges into what is on disk instead of overwriting it."""
        f = self.dir / "job.json"
        if not f.exists():
            raise JobDeleted(f"project {self.id} was deleted")
        return _read(f)

    def set(self, **values) -> None:
        with _lock:
            self.data = {**self._fresh(), **values, "updated": time.time()}
            self.save()

    def log(self, agent: str, message: str, level: str = "info") -> None:
        entry = {"t": time.time(), "agent": agent, "msg": message, "level": level}
        with _lock:
            fresh = self._fresh()
            self.data = {**fresh, "log": [*fresh.get("log", []), entry][-MAX_LOG:], "updated": time.time()}
            self.save()

    def done(self, stage: str) -> bool:
        return stage in self.data.get("done", [])

    def mark(self, stage: str) -> None:
        with _lock:
            done = [s for s in self._fresh().get("done", []) if s != stage]
            self.set(done=[*done, stage])

    def reset_from(self, stages: list[str]) -> None:
        with _lock:
            self.set(done=[s for s in self._fresh().get("done", []) if s not in stages])

    @classmethod
    def create(cls, options: dict, source: dict) -> "Job":
        job = cls(new_id(), {
            "created": time.time(), "status": "queued", "stage": "", "progress": 0,
            "title": source.get("title") or source.get("input", ""), "source": source,
            "options": options, "done": [], "log": [],
        })
        job.save()
        return job

    @classmethod
    def load(cls, job_id: str) -> "Job":
        with _lock:
            data = _read(JOBS / job_id / "job.json")
        return cls(job_id, data)


def all_jobs() -> list[Job]:
    if not JOBS.exists():
        return []
    jobs = []
    for d in JOBS.iterdir():
        if (d / "job.json").exists():
            try:
                jobs.append(Job.load(d.name))
            except (json.JSONDecodeError, OSError):
                continue
    return sorted(jobs, key=lambda j: j.data.get("created", 0), reverse=True)
