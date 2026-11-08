"""Thin ffmpeg helpers (bundled ffmpeg from imageio-ffmpeg, no system install needed)."""
import os
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a child process and everything it started (Remotion spawns Chrome + ffmpeg)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-600:]}")


def probe(path: Path) -> dict:
    """Return duration (s), width, height of the first video stream (if any)."""
    proc = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    err = proc.stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not m:
        raise RuntimeError(f"cannot read media info: {path}")
    h, mi, s = m.groups()
    info = {"duration": int(h) * 3600 + int(mi) * 60 + float(s), "width": 0, "height": 0}
    v = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})[ ,\[]", err)
    if v:
        info["width"], info["height"] = int(v.group(1)), int(v.group(2))
    return info


def extract_audio_16k(video: Path, wav: Path) -> None:
    run_ffmpeg(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])


def grab_frames(video: Path, out_dir: Path, count: int, duration: float, width: int = 960) -> list[Path]:
    """Save `count` evenly spaced frames (scaled to `width`) as PNG."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        out = out_dir / f"f{i:02d}.png"
        run_ffmpeg(["-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)])
        frames.append(out)
    return frames
