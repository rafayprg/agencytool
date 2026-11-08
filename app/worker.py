"""Orchestrator: runs every job through the agent chain on two lanes (pipeline / batch mode).

  prep lane    Downloader → Phone Cropper → Transcriber → Scene Planner → Translator → (Review) → Voice Artist
  editor lane  Video Editor → Thumbnail Artist → Publisher

While the editor lane renders one video (the heavy, CPU-bound part), the prep lane already
prepares the next ones — up to `prep_ahead` videos wait ready for the editor. prep_ahead = 0
gives the old one-video-at-a-time behaviour. State lives in jobs/<id>/job.json, so a restart
picks up where it stopped.
"""
import logging
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Callable

from agents import crop, ingest, library, notify, publish, render, scenes, settings, thumbnail, transcribe, translate, voice
from agents.config import JOBS
from agents.job import Job, JobDeleted, all_jobs

log = logging.getLogger("worker")


@dataclass(frozen=True)
class Agent:
    stage: str
    name: str
    role: str
    run: Callable[[Job, Callable[[float], None]], object]


def _no_progress(fn: Callable[[Job], object]) -> Callable[[Job, Callable[[float], None]], object]:
    return lambda job, _progress: fn(job)


AGENTS = [
    Agent("ingest", "Downloader", "Fetches the video + title/tags from YouTube, Drive, your upload or your downloader's folder", ingest.run),
    Agent("crop", "Phone Cropper", "Finds the phone screen-recording in the frame and cuts it out", _no_progress(crop.run)),
    Agent("transcribe", "Transcriber", "Writes down every spoken word with timings (Whisper, offline, GPU if available)", transcribe.run),
    Agent("scenes", "Scene Planner", "Splits the talk into scenes and spots the buttons to tap", _no_progress(scenes.run)),
    Agent("translate", "Translator", "Translates the script into your language (Groq, Gemini or free engines)", _no_progress(translate.run)),
    Agent("review", "Script Review", "Waits for you to check/edit the translated script (optional)", _no_progress(lambda job: None)),
    Agent("voice", "Voice Artist", "Records each line with the voice you picked (edge-tts, free)", voice.run),
    Agent("render", "Video Editor", "Builds the final edit in your style: phone, captions, headings, music", render.run),
    Agent("thumbnail", "Thumbnail Artist", "Saves the creator's thumbnail and designs a new one in your language", _no_progress(thumbnail.run)),
    Agent("publish", "Publisher", "Packs videos, thumbnails, captions, title, description and tags for upload", _no_progress(publish.run)),
]
STAGE_NAMES = [a.stage for a in AGENTS]
EDITOR_STAGES = ["render", "thumbnail", "publish"]
PREP_STAGES = [s for s in STAGE_NAMES if s not in EDITOR_STAGES]


class JobCancelled(Exception):
    """Raised inside an agent when the user pressed Stop."""


PROGRESS_MIN_STEP = 0.005
PROGRESS_MIN_GAP_SEC = 0.7
THROTTLE_POLL_SEC = 2


def _progress_writer(job: Job) -> Callable[[float], None]:
    """Throttled progress saver that never lets a disk hiccup kill the agent."""
    last = {"value": -1.0, "t": 0.0}

    def progress(frac: float) -> None:
        value = round(max(0.0, min(frac, 1.0)), 3)
        now = time.monotonic()
        if value < 1 and (value - last["value"] < PROGRESS_MIN_STEP or now - last["t"] < PROGRESS_MIN_GAP_SEC):
            return
        last.update(value=value, t=now)
        try:
            job.set(progress=value)
        except OSError as exc:
            log.warning("progress not saved for %s: %s", job.id, exc)
            return
        if job.data.get("status") == "cancelled":
            raise JobCancelled()  # the agent's cleanup stops its subprocess

    return progress


def _fail(job_id: str, message: str) -> None:
    """Never leave a job stuck in 'running' after an unexpected error."""
    try:
        if (JOBS / job_id / "job.json").exists():
            Job.load(job_id).set(status="error", error=message[:400])
            library.report_status(job_id, "error")
            notify.job_failed(job_id)
    except Exception:
        log.exception("could not mark %s as failed", job_id)


def _release_siblings(main: Job, failed: bool) -> None:
    """Language siblings waiting for this project: go on (transcript ready) or stop (main failed)."""
    for sid in main.data.get("siblings", []):
        if not (JOBS / sid / "job.json").exists():
            continue
        sib = Job.load(sid)
        if sib.data.get("status") != "waiting":
            continue
        if failed:
            sib.set(status="error", error=f"Downloader: main project {main.id} failed — retry it, then retry this one")
        else:
            sib.set(status="queued")
            worker.enqueue(sid)


class Lane:
    """One background thread that runs a fixed set of stages for one job at a time."""

    def __init__(self, name: str, stages: list[str], on_finished: Callable[[Job], None],
                 may_start: Callable[[], bool] | None = None) -> None:
        self.name = name
        self.stages = stages
        self.on_finished = on_finished   # called when this lane's stages are all done
        self.may_start = may_start       # throttle: wait before taking the next job
        self.q: queue.Queue[str] = queue.Queue()
        self.queued: set[str] = set()
        self.lock = threading.Lock()
        self.current_id: str | None = None
        self.after_job: Callable[[], None] | None = None
        self.thread = threading.Thread(target=self._loop, name=f"lane-{name}", daemon=True)

    def enqueue(self, job_id: str) -> None:
        with self.lock:
            if job_id in self.queued or job_id == self.current_id:
                return
            self.queued.add(job_id)
        self.q.put(job_id)

    def waiting(self) -> int:
        with self.lock:
            return len(self.queued)

    def _loop(self) -> None:
        while True:
            job_id = self.q.get()
            while self.may_start and not self.may_start():
                time.sleep(THROTTLE_POLL_SEC)
            with self.lock:
                self.queued.discard(job_id)
                self.current_id = job_id
            try:
                if (JOBS / job_id / "job.json").exists():
                    self._run(Job.load(job_id))
            except JobDeleted:
                log.info("job %s was deleted", job_id)
            except Exception as exc:
                log.exception("%s lane crashed on %s", self.name, job_id)
                _fail(job_id, f"Orchestrator: {exc}")
            finally:
                with self.lock:
                    self.current_id = None
                if self.after_job:
                    self.after_job()

    def _run(self, job: Job) -> None:
        if job.data.get("status") == "cancelled":
            return
        job.set(status="running", error="", started=job.data.get("started") or time.time())
        for agent in AGENTS:
            if agent.stage not in self.stages:
                continue
            job = Job.load(job.id)
            if job.data.get("status") != "running":
                job.log("Orchestrator", "stopped by you")
                return
            if job.done(agent.stage):
                continue
            if agent.stage == "review" and job.data["options"].get("review"):
                job.set(status="review", stage="review", progress=0)
                job.log("Script Review", "translation ready — check the script, then press Continue")
                return
            job.set(stage=agent.stage, progress=0)
            try:
                extra = agent.run(job, _progress_writer(job))
            except (JobCancelled, JobDeleted):
                if (JOBS / job.id / "job.json").exists():
                    Job.load(job.id).log("Orchestrator", f"stopped by you during {agent.name}")
                    library.report_status(job.id, "cancelled")
                return
            except ingest.WaitForMain as main_id:
                job = Job.load(job.id)
                job.set(status="waiting", stage="ingest", progress=0)
                job.log("Orchestrator", f"waiting for the main project {main_id} to finish its transcript")
                return
            except Exception as exc:
                log.warning("%s failed on %s: %s", agent.name, job.id, traceback.format_exc())
                job = Job.load(job.id)
                job.log(agent.name, str(exc)[:600], level="error")
                job.set(status="error", error=f"{agent.name}: {str(exc)[:400]}")
                library.report_status(job.id, "error")
                notify.job_failed(job.id)
                _release_siblings(job, failed=True)
                return
            job = Job.load(job.id)
            job.mark(agent.stage)
            job.set(progress=1)
            if agent.stage == "scenes":
                _release_siblings(job, failed=False)
            for child in extra or []:
                worker.enqueue(child.id)
        job = Job.load(job.id)
        if job.data.get("status") != "running":
            job.log("Orchestrator", "stopped by you")
            return
        self.on_finished(job)


class Worker:
    """Two lanes working in parallel; the API and Autopilot only talk to this facade."""

    def __init__(self) -> None:
        self.after_job: Callable[[], None] | None = None
        self.editor = Lane("editor", EDITOR_STAGES, self._editor_finished)
        self.prep = Lane("prep", PREP_STAGES, self._prep_finished, may_start=self._prep_may_start)
        self.editor.after_job = self._after
        self.prep.after_job = self._after

    # ---------- lane hand-off ----------
    def _prep_may_start(self) -> bool:
        """Keep at most `prep_ahead` prepared videos waiting for the editor (0 = strictly one at a time)."""
        ahead = int(settings.load()["prep_ahead"])
        backlog = self.editor.waiting()
        if ahead <= 0:
            return backlog == 0 and self.editor.current_id is None
        return backlog < ahead

    def _prep_finished(self, job: Job) -> None:
        job.set(status="queued", stage="render", progress=0)
        job.log("Orchestrator", "prepared — waiting for the Video Editor")
        self.editor.enqueue(job.id)

    @staticmethod
    def _editor_finished(job: Job) -> None:
        job.set(status="done", stage="", progress=1, finished=time.time())
        job.log("Orchestrator", "all agents finished — your video is ready")
        library.report_status(job.id, "done")
        notify.job_done(job.id)

    def _after(self) -> None:
        if self.after_job:
            self.after_job()

    # ---------- public API ----------
    def start(self) -> None:
        for job in reversed(all_jobs()):
            if job.data.get("status") in ("queued", "running", "waiting"):
                job.set(status="queued")
                self.enqueue(job.id)
        self.prep.thread.start()
        self.editor.thread.start()

    def enqueue(self, job_id: str) -> None:
        """Send a job to the lane that owns its next unfinished stage."""
        job = Job.load(job_id)
        prep_done = all(job.done(s) or (s == "review" and not job.data["options"].get("review")) for s in PREP_STAGES)
        (self.editor if prep_done else self.prep).enqueue(job_id)

    def is_busy(self, job_id: str) -> bool:
        """True while a lane thread is executing this job (even if the user pressed Stop)."""
        return job_id in (self.prep.current_id, self.editor.current_id)

    def snapshot(self) -> dict:
        return {"prep": self.prep.current_id, "editor": self.editor.current_id,
                "prep_waiting": self.prep.waiting(), "editor_waiting": self.editor.waiting()}


worker = Worker()
