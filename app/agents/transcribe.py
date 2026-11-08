"""Transcriber agent: original audio -> timestamped transcript (faster-whisper, local, free)."""
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from . import settings
from .config import PYTHON
from .job import Job
from .media import extract_audio_16k, kill_tree

WORKER = Path(__file__).with_name("whisper_worker.py")
EN_MODELS = {"tiny", "base", "small", "medium"}


def run(job: Job, progress: Callable[[float], None]) -> None:
    wav = job.path("analysis", "audio_16k.wav")
    if not wav.exists():
        extract_audio_16k(job.dir / job.data["video"], wav)
    out = job.path("analysis", "transcript.json")
    size = settings.load()["whisper_model"]
    lang = (job.data.get("language") or "").split("-")[0] or "auto"
    model = f"{size}.en" if lang == "en" and size in EN_MODELS else size
    job.log("Transcriber", f"whisper '{model}' (language: {lang}) — first run downloads the model once")
    device = settings.load()["transcribe_device"]
    proc = subprocess.Popen([str(PYTHON), "-I", str(WORKER), str(wav), str(out), model, lang, device],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf8", errors="replace")
    duration = max(job.data["duration"], 1)
    tail: list[str] = []
    try:
        # one merged stream: a full stderr pipe (model download bars) can never block whisper
        for line in proc.stdout:
            if line.startswith("PROGRESS "):
                progress(min(float(line.split()[1]) / duration, 1.0))
            elif line.startswith("DEVICE "):
                job.log("Transcriber", "running on " + ("the graphics card" if line.split()[1] == "gpu" else "the CPU")
                        + (" (graphics card not usable: " + line.split("(", 1)[1].rstrip() if "failed" in line else ""))
            elif line.strip():
                tail = [*tail, line.strip()][-8:]
        err = " | ".join(tail)
        code = proc.wait()
    finally:
        if proc.poll() is None:
            kill_tree(proc)
    if code != 0:
        raise RuntimeError(f"whisper failed: {err.strip()[-500:]}")
    result = json.loads(out.read_text(encoding="utf8"))
    if not result["segments"]:
        raise RuntimeError("no speech found in this video")
    if not job.data.get("language"):
        job.set(language=result["language"])
    job.log("Transcriber", f"{len(result['segments'])} lines, spoken language: {result['language']}")
