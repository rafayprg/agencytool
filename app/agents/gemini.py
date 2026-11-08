"""Optional Google AI Studio (Gemini) client — free tier key from aistudio.google.com.
Everything in the platform works without it; with it, translations and headings get better."""
import base64
import json
import logging
import time
from pathlib import Path

import httpx

from . import settings

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 120
RETRIES = 3


class GeminiError(RuntimeError):
    pass


def _message(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"][:200]
    except (ValueError, KeyError, TypeError):
        return r.text[:200]


def configured() -> bool:
    return bool(settings.load()["gemini_api_key"])


def _key() -> str:
    key = settings.load()["gemini_api_key"]
    if not key:
        raise GeminiError("Gemini API key not set (Settings)")
    return key


def list_models(key: str | None = None) -> list[str]:
    r = httpx.get(f"{BASE}/models", params={"pageSize": 200}, headers={"x-goog-api-key": key or _key()}, timeout=30)
    if r.status_code != 200:
        raise GeminiError(f"Gemini rejected the key: {_message(r)}")
    models = r.json().get("models", [])
    return sorted(
        m["name"].removeprefix("models/") for m in models
        if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m["name"]
    )


def generate_json(prompt: str, image: Path | None = None) -> dict | list:
    """One prompt (+ optional image) -> parsed JSON answer. Retries on rate limits."""
    parts: list[dict] = [{"text": prompt}]
    if image is not None:
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(image.read_bytes()).decode()}})
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    model = settings.load()["gemini_model"]
    for attempt in range(1, RETRIES + 1):
        r = httpx.post(f"{BASE}/models/{model}:generateContent", headers={"x-goog-api-key": _key()}, json=body, timeout=TIMEOUT)
        if r.status_code in (429, 500, 503) and attempt < RETRIES:
            time.sleep(10 * attempt)
            continue
        if r.status_code != 200:
            raise GeminiError(f"Gemini error {r.status_code}: {_message(r)}")
        try:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise GeminiError(f"Gemini returned an unexpected answer: {exc}") from exc
    raise GeminiError("Gemini unavailable")
