"""Optional Telegram messages (free bot from @BotFather): video ready / failed / autopilot paused.
Never raises — a notification problem must not stop a video."""
import json
import logging
import threading

import httpx

from . import settings
from .config import JOBS

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 15


def configured() -> bool:
    s = settings.load()
    return bool(s["telegram_bot_token"] and s["telegram_chat_id"])


def send_now(text: str, token: str | None = None, chat_id: str | None = None) -> None:
    """Send immediately; raises on failure (used by the Settings 'Test' button)."""
    s = settings.load()
    token, chat_id = token or s["telegram_bot_token"], chat_id or s["telegram_chat_id"]
    if not token or not chat_id:
        raise RuntimeError("set the Telegram bot token and chat id first")
    r = httpx.post(API.format(token=token), json={"chat_id": chat_id, "text": text[:4000]}, timeout=TIMEOUT)
    if r.status_code != 200:
        try:
            msg = r.json().get("description", r.text)
        except ValueError:
            msg = r.text
        raise RuntimeError(f"Telegram refused: {msg[:200]}")


def send(text: str) -> None:
    """Fire-and-forget in a background thread."""
    if not configured():
        return

    def _go() -> None:
        try:
            send_now(text)
        except Exception as exc:
            log.warning("telegram message not sent: %s", exc)

    threading.Thread(target=_go, name="telegram", daemon=True).start()


def _job(job_id: str) -> dict:
    try:
        return json.loads((JOBS / job_id / "job.json").read_text(encoding="utf8"))
    except (OSError, ValueError):
        return {}


def job_done(job_id: str) -> None:
    s = settings.load()
    if not s["notify_done"]:
        return
    d = _job(job_id)
    minutes = (d.get("finished", 0) - d.get("started", 0)) / 60 if d.get("started") else 0
    send(f"✅ Ready: {d.get('title', job_id)}\nLanguage: {d.get('options', {}).get('lang', '')} · took {minutes:.0f} min")


def job_failed(job_id: str) -> None:
    s = settings.load()
    if not s["notify_errors"]:
        return
    d = _job(job_id)
    send(f"❌ Failed: {d.get('title', job_id)}\n{d.get('error', '')[:300]}")
