"""Thumbnail Artist: keeps the original creator's thumbnail and makes a new 1280x720 one
in the chosen style — translated hook words, a "step by step" badge and the phone showing
the key screen of the tutorial (Remotion still, free)."""
import json
import subprocess

from . import styles
from .config import STUDIO
from .job import Job
from .media import run_ffmpeg
from .render import _npx
from .translate import short_hook
from .voice import link_assets, render_dir

GUIDE_BADGE = {
    "es": "PASO A PASO", "pt": "PASSO A PASSO", "fr": "ÉTAPE PAR ÉTAPE", "de": "SCHRITT FÜR SCHRITT",
    "it": "PASSO DOPO PASSO", "hi": "स्टेप बाय स्टेप", "ur": "مرحلہ وار", "ar": "خطوة بخطوة",
    "tr": "ADIM ADIM", "id": "LANGKAH DEMI LANGKAH", "ru": "ШАГ ЗА ШАГОМ", "ja": "ステップごと",
    "ko": "단계별 가이드", "zh": "分步教程", "en": "STEP BY STEP",
}
ORIGINAL_EXTS = ("jpg", "jpeg", "png", "webp")


def save_original(job: Job) -> bool:
    """Original creator's thumbnail -> publish-ready JPG in render/original_thumbnail.jpg."""
    for ext in ORIGINAL_EXTS:
        src = job.dir / "source" / f"video.{ext}"
        if src.exists():
            run_ffmpeg(["-i", str(src), "-frames:v", "1", "-q:v", "2", str(render_dir(job) / "original_thumbnail.jpg")])
            return True
    return False


def _words(text: str) -> set[str]:
    return {w.strip(".,:;!?¿¡()\"'").lower() for w in text.split() if len(w) > 3}


def key_frame_time(scenes: list[dict], duration: float, title: str = "") -> float:
    """The tap scene that best matches the title (e.g. 'passwords' -> the Password Manager screen);
    ties go to the scene nearest the middle of the tutorial."""
    taps = [sc for sc in scenes if sc.get("callout")]
    if not taps:
        return duration / 2
    want = _words(title)
    mid = len(taps) / 2

    def score(item: tuple[int, dict]) -> tuple[int, float]:
        i, sc = item
        return (len(want & _words(sc["callout"] + " " + sc.get("text", ""))), -abs(i - mid))

    _, best = max(enumerate(taps), key=score)
    s0, s1 = best["src"]
    return min(s0 + (s1 - s0) * 0.7, max(duration - 0.5, 0))  # late in the scene: after the tap happened


def run(job: Job) -> None:
    out_dir = render_dir(job)
    link_assets(job)
    has_original = save_original(job)
    spec = json.loads(job.path("script", "scenes.json").read_text(encoding="utf8"))
    t = key_frame_time(spec["scenes"], job.data["duration"], spec["title"])
    run_ffmpeg(["-ss", f"{t:.2f}", "-i", str(job.dir / "analysis" / "phone.mp4"), "-frames:v", "1", "-q:v", "2",
                str(out_dir / "public" / "phone_thumb.jpg")])
    crop = job.data["crop"]
    props = {
        "theme": styles.get(job.data["options"].get("style") or "neon-night"),
        "text": (spec.get("thumb_text") or short_hook(spec["title"])).strip()[:60],
        "badge": GUIDE_BADGE.get(spec["lang"], GUIDE_BADGE["en"]),
        "phoneImage": "phone_thumb.jpg",
        "phone": {"w": crop["w"], "h": crop["h"]},
    }
    props_file = out_dir / "thumb_props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf8")
    out = out_dir / "thumbnail.jpg"
    out.unlink(missing_ok=True)
    proc = subprocess.run([_npx(), "remotion", "still", "src/index.ts", "Thumbnail", str(out), f"--props={props_file}",
                           f"--public-dir={out_dir / 'public'}", "--image-format=jpeg", "--jpeg-quality=92", "--log=error"],
                          cwd=STUDIO, capture_output=True, text=True, encoding="utf8", errors="replace")
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("thumbnail render failed: " + (proc.stderr or proc.stdout).strip()[-400:])
    job.log("Thumbnail Artist", f"new thumbnail “{props['text']}”" + (" + original saved" if has_original else " (no original thumbnail found)"))
