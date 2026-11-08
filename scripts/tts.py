"""Generate per-scene voice-over + word timings with edge-tts, then write a Remotion timeline.

Usage: tts.py <scenes.json> <out_audio_dir> <timeline.json>
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import edge_tts
import imageio_ffmpeg

FPS = 30
GAP_SEC = 0.35  # silence after each scene's line
TICKS_PER_SEC = 10_000_000


def mp3_duration(path: Path) -> float:
    proc = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", proc.stderr)
    if not m:
        raise RuntimeError(f"no duration for {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


async def synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    words: list[dict] = []
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


async def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf8"))
    audio_dir = Path(sys.argv[2])
    audio_dir.mkdir(parents=True, exist_ok=True)
    timeline = []
    cursor = 0
    for sc in spec["scenes"]:
        mp3 = audio_dir / f"vo_{sc['id']:02d}.mp3"
        words = await synth(sc["text"], spec["voice"], spec["rate"], mp3)
        dur = mp3_duration(mp3)
        frames = round((dur + GAP_SEC) * FPS)
        timeline.append({**sc, "audio": f"vo/{mp3.name}", "from": cursor, "frames": frames, "voiceSec": dur, "words": words})
        print(f"scene {sc['id']:2d}: {dur:5.2f}s  src {sc['src'][1]-sc['src'][0]:3d}s  words {len(words)}")
        cursor += frames
    Path(sys.argv[3]).write_text(json.dumps({"title": spec["title"], "fps": FPS, "total": cursor, "scenes": timeline}, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"total {cursor / FPS:.1f}s")


asyncio.run(main())
