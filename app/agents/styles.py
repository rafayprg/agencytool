"""Style Designer agent: editing-style presets (styles/*.json) and new styles made
from a reference image or video (local colour analysis; Gemini adds the mood if a key is set)."""
import colorsys
import json
import re
import time
from pathlib import Path

from PIL import Image

from . import gemini
from .config import STYLES, VIDEO_EXTS
from .media import grab_frames, probe

STYLE_ID_RE = re.compile(r"^[a-z0-9-]{2,60}$")
FONTS = {
    "modern": "'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
    "bold": "'Arial Black', 'Segoe UI Black', Impact, sans-serif",
    "friendly": "'Trebuchet MS', 'Segoe UI', sans-serif",
    "classic": "Georgia, 'Times New Roman', serif",
}
REQUIRED_COLORS = ("bg1", "bg2", "accent", "accent2", "text")


def list_styles() -> list[dict]:
    out = []
    for f in sorted(STYLES.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf8")))
        except json.JSONDecodeError:
            continue
    return out


def get(style_id: str) -> dict:
    if not STYLE_ID_RE.match(style_id or ""):
        raise ValueError("bad style id")
    f = STYLES / f"{style_id}.json"
    if not f.exists():
        f = STYLES / "neon-night.json"
    return json.loads(f.read_text(encoding="utf8"))


def save(style: dict) -> dict:
    if not STYLE_ID_RE.match(style.get("id", "")):
        raise ValueError("style id must be lowercase letters, digits and dashes")
    colors = style.get("colors", {})
    if any(not re.match(r"^#[0-9a-fA-F]{6}$", colors.get(k, "")) for k in REQUIRED_COLORS):
        raise ValueError("every colour must be a #rrggbb value")
    if style.get("layout") not in ("phone-right", "phone-left"):
        raise ValueError("layout must be phone-right or phone-left")
    clean = {
        "id": style["id"], "name": str(style.get("name", style["id"]))[:40],
        "description": str(style.get("description", ""))[:200],
        "colors": {k: colors[k] for k in REQUIRED_COLORS},
        "font": style.get("font") if style.get("font") in FONTS.values() else FONTS["modern"],
        "captionScale": max(0.7, min(1.4, float(style.get("captionScale", 1)))),
        "layout": style["layout"], "grid": bool(style.get("grid", True)),
        "music": bool(style.get("music", True)), "musicVolume": max(0.0, min(0.3, float(style.get("musicVolume", 0.07)))),
    }
    (STYLES / f"{clean['id']}.json").write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf8")
    return clean


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _palette(img: Path, count: int = 8) -> list[tuple[tuple[int, int, int], int]]:
    im = Image.open(img).convert("RGB").resize((240, 240))
    q = im.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: count * 3]
    counts = sorted(q.getcolors(), reverse=True)
    return [((pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]), n) for n, i in counts]


def _hls(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def _from_hls(h: float, l: float, s: float) -> tuple[int, int, int]:
    return tuple(int(c * 255) for c in colorsys.hls_to_rgb(h % 1.0, l, s))


def derive_colors(pal: list[tuple[tuple[int, int, int], int]]) -> dict:
    """Background from the most common non-extreme colour, accents from the most vivid ones."""
    total = sum(n for _, n in pal) or 1
    mids = [(c, n) for c, n in pal if 0.08 < _hls(c)[1] < 0.9]
    base, base_n = max(mids, key=lambda x: x[1]) if mids else pal[0]
    # a bright white/black frame only wins if it really fills most of the picture
    if pal[0][1] / total > 0.55:
        base = pal[0][0]
    h, l, sat = _hls(base)
    dark = l < 0.6
    if dark:
        bg1, bg2 = _from_hls(h, min(l, 0.12), min(sat, 0.6)), _from_hls(h, min(l + 0.12, 0.3), min(sat, 0.6))
    else:
        bg1, bg2 = _from_hls(h, max(l, 0.92), min(sat, 0.35)), _from_hls(h, 0.99, min(sat, 0.3))
    vivid = sorted(
        (c for c, n in pal if _hls(c)[2] > 0.35 and 0.3 < _hls(c)[1] < 0.75 and n / total > 0.004),
        key=lambda c: _hls(c)[2] * (1 - abs(_hls(c)[1] - 0.5)), reverse=True,
    )
    accent = vivid[0] if vivid else _from_hls(h + 0.5, 0.6, 0.85)
    ah = _hls(accent)[0]
    accent2 = next((c for c in vivid[1:] if min(abs(_hls(c)[0] - ah), 1 - abs(_hls(c)[0] - ah)) > 0.12), None)
    if accent2 is None:
        accent2 = _from_hls(ah + 0.45, 0.55 if dark else 0.45, 0.75)
    if not dark and _hls(accent)[1] > 0.6:
        accent = _from_hls(ah, 0.45, _hls(accent)[2])  # keep highlights readable on light backgrounds
    return {"bg1": _hex(bg1), "bg2": _hex(bg2), "accent": _hex(accent), "accent2": _hex(accent2),
            "text": "#ffffff" if dark else "#101828"}, dark


def from_reference(ref: Path, name: str) -> dict:
    """Build a style from an image or a video frame."""
    image = ref
    if ref.suffix.lower() in VIDEO_EXTS:
        frames = grab_frames(ref, ref.parent / (ref.stem + "_frames"), 1, probe(ref)["duration"], 640)
        image = frames[0]
    colors, dark = derive_colors(_palette(image, 16))
    style = {
        "id": "ref-" + time.strftime("%Y%m%d-%H%M%S"),
        "name": name or "From reference",
        "description": f"Made from {ref.name}",
        "colors": colors,
        "font": FONTS["modern"], "captionScale": 1, "layout": "phone-right",
        "grid": dark, "music": True, "musicVolume": 0.07,
    }
    if gemini.configured():
        style = _gemini_refine(style, image)
    return save(style)


def _gemini_refine(style: dict, image: Path) -> dict:
    prompt = (
        "This is a reference frame for the editing style of a phone-tutorial video. "
        f"Our colour analysis gave: {json.dumps(style['colors'])}. Improve it so captions stay readable. "
        f"Return JSON: {{\"name\": str (2-3 words), \"description\": str (one sentence), "
        f"\"colors\": {{\"bg1\",\"bg2\",\"accent\",\"accent2\",\"text\"}} as #rrggbb, "
        f"\"font\": one of {list(FONTS)}, \"layout\": \"phone-right\" or \"phone-left\", \"grid\": bool, \"captionScale\": 0.9-1.2}}"
    )
    try:
        res = gemini.generate_json(prompt, image)
        colors = {**style["colors"], **{k: v for k, v in res.get("colors", {}).items() if k in REQUIRED_COLORS}}
        return {**style, "name": res.get("name") or style["name"], "description": res.get("description") or style["description"],
                "colors": colors, "font": FONTS.get(res.get("font"), style["font"]),
                "layout": res.get("layout", style["layout"]), "grid": bool(res.get("grid", style["grid"])),
                "captionScale": res.get("captionScale", 1)}
    except Exception:
        return style
