"""Stage 6: per-scene voice-over with edge-tts (free) + word timings -> Remotion timeline."""
import asyncio
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import edge_tts

from .config import FPS, SHARED_ASSETS, STUDIO
from .job import Job
from .media import probe

GAP_SEC = 0.35  # breath after each line
TICKS_PER_SEC = 10_000_000
RETRIES = 5  # network blips (DNS, timeouts) are common on long unattended runs


async def synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    for attempt in range(1, RETRIES + 1):
        words: list[dict] = []
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
            with out.open("wb") as f:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        words.append({
                            "w": chunk["text"],
                            "s": round(chunk["offset"] / TICKS_PER_SEC, 3),
                            "e": round((chunk["offset"] + chunk["duration"]) / TICKS_PER_SEC, 3),
                        })
            return words
        except Exception as exc:
            if attempt == RETRIES:
                raise RuntimeError(f"edge-tts failed for '{text[:40]}…': {exc}") from exc
            await asyncio.sleep(5 * attempt)
    return []


def render_dir(job: Job) -> Path:
    return job.dir / "render"


async def _build(job: Job, progress: Callable[[float], None]) -> dict:
    spec = json.loads(job.path("script", "scenes.json").read_text(encoding="utf8"))
    public = render_dir(job) / "public"
    (public / "vo").mkdir(parents=True, exist_ok=True)
    timeline, cursor = [], 0
    total = len(spec["scenes"])
    for i, sc in enumerate(spec["scenes"]):
        if not sc["text"].strip():
            raise RuntimeError(f"scene {sc['id']} has no text — fix it in the script editor")
        mp3 = public / "vo" / f"vo_{sc['id']:03d}.mp3"
        words = await synth(sc["text"], spec["voice"], spec["rate"], mp3)
        dur = probe(mp3)["duration"]
        frames = round((dur + GAP_SEC) * FPS)
        timeline.append({**sc, "audio": f"vo/{mp3.name}", "from": cursor, "frames": frames, "voiceSec": dur, "words": words})
        cursor += frames
        progress((i + 1) / total)
    crop = job.data["crop"]
    return {
        "title": spec["title"],
        "lang": spec["lang"],
        "fps": FPS,
        "total": cursor,
        "phone": {"w": crop["w"], "h": crop["h"]},
        "labels": spec.get("labels", {"tap": "TAP"}),
        "scenes": timeline,
    }


def link_assets(job: Job) -> None:
    """Phone footage + music/sfx into the render's public folder (re-run after a re-crop)."""
    public = render_dir(job) / "public"
    shutil.copy2(job.dir / "analysis" / "phone.mp4", public / "phone.mp4")
    for name in SHARED_ASSETS:
        if not (public / name).exists():
            shutil.copy2(STUDIO / "public" / name, public / name)


def run(job: Job, progress: Callable[[float], None]) -> None:
    out_dir = render_dir(job)
    shutil.rmtree(out_dir / "public" / "vo", ignore_errors=True)
    timeline = asyncio.run(_build(job, progress))
    (out_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf8")
    job.log("Voice Artist", f"{len(timeline['scenes'])} voice lines, video length {timeline['total'] / FPS:.0f}s")
