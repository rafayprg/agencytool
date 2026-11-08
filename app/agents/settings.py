"""User settings stored in data/settings.json (local only, never committed)."""
import json
import threading

from .config import DATA

DEFAULTS = {
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "groq_api_key": "",
    "groq_model": "llama-3.3-70b-versatile",
    "translator": "auto",        # auto (Groq -> Gemini -> free) | groq | gemini | free
    "mymemory_email": "",        # optional: raises MyMemory free quota from 5k to 50k chars/day
    "whisper_model": "small",    # tiny | base | small | medium (bigger = slower, more accurate)
    "default_lang": "es",
    "default_voice": "es-MX-JorgeNeural",
    "default_style": "neon-night",
    "review_script": True,       # pause after translation so the script can be edited
    "prep_ahead": 2,             # pipeline: videos prepared while the editor renders (0 = one at a time)
    "transcribe_device": "auto", # auto (graphics card if it works, else CPU) | cpu | gpu
    "cleanup_after_done": False, # delete working files of finished manual projects (Autopilot has its own switch)
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "notify_done": True,
    "notify_errors": True,
    "library_dir": "",           # optional shared folder (e.g. a network share) so two PCs share one Library
}
_FILE = DATA / "settings.json"
_lock = threading.Lock()


def load() -> dict:
    with _lock:
        if not _FILE.exists():
            return dict(DEFAULTS)
        saved = json.loads(_FILE.read_text(encoding="utf8"))
        return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def save(values: dict) -> dict:
    current = load()
    merged = {**current, **{k: v for k, v in values.items() if k in DEFAULTS}}
    with _lock:
        DATA.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf8")
    return merged


def _mask(key: str) -> str:
    return f"••••{key[-4:]}" if key else ""


def public(values: dict) -> dict:
    """Settings for the browser: API keys are masked."""
    return {**values,
            "gemini_api_key": _mask(values.get("gemini_api_key", "")),
            "groq_api_key": _mask(values.get("groq_api_key", "")),
            "telegram_bot_token": _mask(values.get("telegram_bot_token", "")),
            "gemini_configured": bool(values.get("gemini_api_key")),
            "groq_configured": bool(values.get("groq_api_key")),
            "telegram_configured": bool(values.get("telegram_bot_token") and values.get("telegram_chat_id"))}
