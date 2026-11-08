"""Stage 2: find the phone screen-recording inside the frame and cut it out.

Order of preference: --crop flag > crop_presets.json (by channel) > auto-detect.
Auto-detect looks for the tall, bright, low-saturation rectangle that the phone
screen makes across many frames (works for light-mode screen recordings).
Always writes analysis/crop_preview.jpg so a human can check it.
"""
import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image

from .config import CROP_PRESETS
from .job import Job
from .media import grab_frames, run_ffmpeg

log = logging.getLogger(__name__)
SAMPLE_FRAMES = 16
DETECT_WIDTH = 960
BRIGHT = 185          # luminance threshold for "screen-like" pixels
MAX_SAT = 60          # screens are mostly grey/white; skin and walls are not
COL_FILL = 0.45       # column counts as screen if this share of its rows is bright
ROW_FILL = 0.30
MIN_W, MAX_W = 0.08, 0.6  # plausible phone width as share of frame width
MIN_ASPECT = 1.4          # phone screen is portrait (h/w)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, v in enumerate([*mask, False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    return runs


def detect(frames: list[Path]) -> tuple[int, int, int, int] | None:
    """Return crop (w, h, x, y) in DETECT_WIDTH pixel space, or None."""
    masks = []
    for f in frames:
        rgb = np.asarray(Image.open(f).convert("RGB")).astype(np.int16)
        lum = rgb.mean(axis=2)
        sat = rgb.max(axis=2) - rgb.min(axis=2)
        masks.append((lum > BRIGHT) & (sat < MAX_SAT))
    mask = np.median(np.stack(masks), axis=0) > 0.5
    height, width = mask.shape
    col_runs = [r for r in _runs(mask.mean(axis=0) > COL_FILL) if MIN_W * width <= r[1] - r[0] <= MAX_W * width]
    if not col_runs:
        return None
    x0, x1 = max(col_runs, key=lambda r: r[1] - r[0])
    rows = mask[:, x0:x1].mean(axis=1) > ROW_FILL
    y_runs = _runs(rows)
    if not y_runs:
        return None
    y0, y1 = max(y_runs, key=lambda r: r[1] - r[0])
    if (y1 - y0) / (x1 - x0) < MIN_ASPECT:
        return None
    return x1 - x0, y1 - y0, x0, y0


def _even(v: float) -> int:
    return int(round(v / 2) * 2)


def _preset(channel: str) -> str | None:
    if not CROP_PRESETS.exists() or not channel:
        return None
    return json.loads(CROP_PRESETS.read_text(encoding="utf8")).get(channel)


def run(job: Job) -> None:
    video = job.dir / job.data["video"]
    crop_arg = (job.data["options"].get("crop") or "").strip()
    spec = crop_arg or _preset(job.data.get("channel", ""))
    source = "manual" if crop_arg else "channel preset"
    if not spec:
        frames = grab_frames(video, job.dir / "analysis" / "frames", SAMPLE_FRAMES, job.data["duration"], DETECT_WIDTH)
        found = detect(frames)
        if not found:
            raise RuntimeError(
                "phone screen not found automatically (dark-mode app, or no phone in the frame). "
                "Open the job, set the crop box by hand (W:H:X:Y) and press Retry."
            )
        scale = job.data["width"] / DETECT_WIDTH
        spec = ":".join(str(_even(v * scale)) for v in found)
        source = "auto-detect"
    w, h, x, y = parse_crop(spec, job.data["width"], job.data["height"])
    phone = job.path("analysis", "phone.mp4")
    run_ffmpeg(["-i", str(video), "-an", "-vf", f"crop={w}:{h}:{x}:{y}", "-c:v", "libx264", "-crf", "18",
                "-preset", "fast", "-pix_fmt", "yuv420p", str(phone)])
    mid = job.data["duration"] / 2
    run_ffmpeg(["-ss", f"{mid:.1f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(job.path("analysis", "full_frame.jpg"))])
    run_ffmpeg(["-ss", f"{mid:.1f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", "-vf", f"crop={w}:{h}:{x}:{y}",
                str(job.path("analysis", "crop_preview.jpg"))])
    job.set(crop={"w": w, "h": h, "x": x, "y": y, "source": source})
    job.log("Phone Cropper", f"phone screen {w}x{h} at ({x},{y}) — {source}")


def parse_crop(spec: str, width: int, height: int) -> tuple[int, int, int, int]:
    try:
        w, h, x, y = (int(float(v)) for v in spec.split(":"))
    except ValueError as exc:
        raise RuntimeError(f"crop must look like W:H:X:Y, got '{spec}'") from exc
    w, h = _even(w), _even(h)
    if w < 50 or h < 50 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise RuntimeError(f"crop {spec} is outside the {width}x{height} video")
    return w, h, x, y
