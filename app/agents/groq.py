"""Optional Groq client (free tier key from console.groq.com) — OpenAI-compatible chat API.
Used by the Translator (JSON answers). Everything works without it."""
import json
import time

import httpx

from . import settings

BASE = "https://api.groq.com/openai/v1"
TIMEOUT = 120
RETRIES = 3
SKIP_WORDS = ("whisper", "tts", "guard", "playai", "orpheus", "distil", "compound", "prompt")
PREFERRED = ("gpt-oss-120b", "llama-3.3-70b", "70b", "gpt-oss", "llama-4", "qwen")


class GroqError(RuntimeError):
    pass


def _message(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"][:200]
    except (ValueError, KeyError, TypeError):
        return r.text[:200]


def configured() -> bool:
    return bool(settings.load()["groq_api_key"])


def _key() -> str:
    key = settings.load()["groq_api_key"]
    if not key:
        raise GroqError("Groq API key not set (Settings)")
    return key


def list_models(key: str | None = None) -> list[str]:
    r = httpx.get(f"{BASE}/models", headers={"Authorization": f"Bearer {key or _key()}"}, timeout=30)
    if r.status_code != 200:
        raise GroqError(f"Groq rejected the key: {_message(r)}")
    ids = [m["id"] for m in r.json().get("data", []) if m.get("active", True)]
    return sorted(i for i in ids if not any(w in i.lower() for w in SKIP_WORDS))


def best_model(models: list[str]) -> str:
    for hint in PREFERRED:
        for m in models:
            if hint in m:
                return m
    return models[0] if models else ""


def generate_json(prompt: str) -> dict | list:
    """One prompt -> parsed JSON answer. Retries on rate limits (free tier)."""
    body = {
        "model": settings.load()["groq_model"],
        "messages": [{"role": "system", "content": "Reply with one valid JSON object only."},
                     {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
    }
    for attempt in range(1, RETRIES + 1):
        r = httpx.post(f"{BASE}/chat/completions", headers={"Authorization": f"Bearer {_key()}"}, json=body, timeout=TIMEOUT)
        if r.status_code in (429, 500, 502, 503) and attempt < RETRIES:
            wait = float(r.headers.get("retry-after", 0) or 0)
            time.sleep(min(max(wait, 10 * attempt), 60))
            continue
        if r.status_code != 200:
            raise GroqError(f"Groq error {r.status_code}: {_message(r)}")
        try:
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise GroqError(f"Groq returned an unexpected answer: {exc}") from exc
    raise GroqError("Groq unavailable")
