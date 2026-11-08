"""Video Editor agent: renders the Remotion studio with this job's timeline, style and media."""
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable

from . import styles
from .config import STUDIO
from .job import Job
from .media import kill_tree
from .voice import link_assets, render_dir

COMPOSITIONS = {"16x9": "TutorialWide", "9x16": "TutorialVertical"}
PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
LINE_SPLIT_RE = re.compile(r"[\r\n]")  # Remotion redraws progress with \r


def _npx() -> str:
    exe = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if not exe:
        raise RuntimeError("Node.js not found — install Node 20+ and run setup again")
    return exe


def _concurrency() -> int:
    """Leave two threads for the OS + the studio server; Remotion tabs also need RAM."""
    return max(1, min((os.cpu_count() or 4) - 2, 8))


def _run_remotion(cmd: list[str], on_progress: Callable[[float], None]) -> list[str]:
    """Run a Remotion render, report progress, and always stop it if anything goes wrong."""
    proc = subprocess.Popen(cmd, cwd=STUDIO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf8", errors="replace")
    tail: list[str] = []
    buf = ""
    try:
        while chunk := proc.stdout.read(256):
            buf += chunk
            parts = LINE_SPLIT_RE.split(buf)
            buf = parts.pop()
            for line in parts:
                if not line.strip():
                    continue
                tail = [*tail, line][-15:]
                m = PROGRESS_RE.search(line) if "Rendered" in line or "Encoded" in line else None
                if m and int(m.group(2)) > 0:
                    on_progress(int(m.group(1)) / int(m.group(2)))
        if proc.wait() != 0:
            raise RuntimeError("render failed: " + " | ".join(tail[-5:])[:600])
    finally:
        if proc.poll() is None:
            kill_tree(proc)
    return tail


def run(job: Job, progress: Callable[[float], None]) -> None:
    out_dir = render_dir(job)
    link_assets(job)
    timeline = json.loads((out_dir / "timeline.json").read_text(encoding="utf8"))
    crop = job.data["crop"]
    timeline = {**timeline, "phone": {"w": crop["w"], "h": crop["h"]}}  # a re-crop may change the shape
    opts = job.data["options"]
    theme = styles.get(opts.get("style") or "neon-night")
    props = out_dir / "props.json"
    props.write_text(json.dumps({"timeline": timeline, "theme": theme}, ensure_ascii=False), encoding="utf8")
    formats = [f for f in opts.get("formats", ["16x9", "9x16"]) if f in COMPOSITIONS]
    if not formats:
        raise RuntimeError("choose at least one output format")
    for idx, fmt in enumerate(formats):
        out = out_dir / f"final_{fmt}.mp4"
        out.unlink(missing_ok=True)
        job.log("Video Editor", f"rendering {fmt} with style '{theme['name']}'")
        cmd = [_npx(), "remotion", "render", "src/index.ts", COMPOSITIONS[fmt], str(out),
               f"--props={props}", f"--public-dir={out_dir / 'public'}", f"--concurrency={_concurrency()}"]
        tail = _run_remotion(cmd, lambda frac, i=idx: progress((i + frac) / len(formats)))
        if not out.exists():
            raise RuntimeError("render failed: " + " | ".join(tail[-5:])[:600])
    job.log("Video Editor", "render finished: " + ", ".join(formats))
