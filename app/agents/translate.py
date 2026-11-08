"""Translator agent: translates the original lines (a translation, not a rewrite) into
the target language and writes script/scenes.json — the file voice + render read.

Engine chain (all free): Gemini (if a key is set) -> Google free web -> MyMemory.
Gemini also writes short step headings; without it headings come from simple rules.
"""
import json
import logging
import time

from . import gemini, groq, settings
from .config import DEFAULT_RATE, LANGUAGES, UI_LABELS
from .job import Job

log = logging.getLogger(__name__)
MYMEMORY_LIMIT = 480
QUOTA_MARK = "MYMEMORY WARNING"
MAX_TAGS = 12
GOOGLE_CHUNK = 4000      # characters per request (lines joined with newlines)
REQUEST_GAP_SEC = 0.35   # stay under the free endpoints' rate limits
# MyMemory wants full locale codes
MYMEMORY_LOCALES = {
    "en": "en-US", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR", "de": "de-DE", "it": "it-IT", "hi": "hi-IN",
    "ur": "ur-PK", "ar": "ar-SA", "tr": "tr-TR", "id": "id-ID", "ru": "ru-RU", "ja": "ja-JP", "ko": "ko-KR", "zh": "zh-CN",
}


def _chunks(texts: list[str], limit: int) -> list[list[str]]:
    out, cur, size = [], [], 0
    for t in texts:
        if cur and size + len(t) + 1 > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(t)
        size += len(t) + 1
    return [*out, cur] if cur else out


def _google(texts: list[str], src: str, dst: str) -> list[str]:
    from deep_translator import GoogleTranslator

    tr = GoogleTranslator(source=src, target=dst)
    clean = [t.replace("\n", " ").strip() for t in texts]
    out: list[str] = []
    for chunk in _chunks(clean, GOOGLE_CHUNK):
        joined = tr.translate("\n".join(c or "." for c in chunk)) or ""
        parts = [p.strip() for p in joined.split("\n")]
        if len(parts) != len(chunk):  # newlines got merged: fall back to one request per line
            parts = []
            for c in chunk:
                parts.append(tr.translate(c) if c else c)
                time.sleep(REQUEST_GAP_SEC)
        out.extend(p if c else c for p, c in zip(parts, chunk))
        time.sleep(REQUEST_GAP_SEC)
    return out


def _mymemory(texts: list[str], src: str, dst: str) -> list[str]:
    from deep_translator import MyMemoryTranslator

    email = settings.load()["mymemory_email"] or None
    source, target = MYMEMORY_LOCALES.get(src, src), MYMEMORY_LOCALES.get(dst, dst)
    tr = MyMemoryTranslator(source=source, target=target, email=email) if email else MyMemoryTranslator(source=source, target=target)
    out = []
    for t in texts:
        if not t.strip():
            out.append(t)
            continue
        res = tr.translate(t[:MYMEMORY_LIMIT])
        if not res or QUOTA_MARK in res:
            raise RuntimeError("MyMemory daily free quota used up (add your email in Settings for 10x more)")
        out.append(res)
        time.sleep(REQUEST_GAP_SEC)
    return out


def _short(exc: Exception) -> str:
    return str(exc).splitlines()[0][:160]


def translate_texts(texts: list[str], src: str, dst: str) -> tuple[list[str], str]:
    """Plain machine translation with fallbacks. Returns (texts, engine used)."""
    if src == dst:
        return list(texts), "none"
    errors = []
    for name, fn in (("google", _google), ("mymemory", _mymemory)):
        try:
            return fn(texts, src, dst), name
        except Exception as exc:
            errors.append(f"{name}: {_short(exc)}")
            log.warning("%s translation failed: %s", name, _short(exc))
    raise RuntimeError("free translators unavailable right now — retry later or add a free Gemini key in Settings. "
                       + " | ".join(errors))


LLM_PROMPT = """You are localizing a phone tutorial video from {src_name} into {dst_name}.
Translate faithfully (keep the meaning and order, natural spoken {dst_name}, no additions).
Keep app/menu/button names as they appear on a {dst_name} phone (translate them the way the app UI does).
Return JSON: {{"title": str, "tags": [str], "tap_label": str (one short word for "TAP"),
"intro_label": str (one word for "Introduction"), "step_label": str (one word for "Step"),
"scenes": [{{"id": int, "text": str, "callout": str, "heading": str}}]}}
- text: the translated spoken line.
- callout: translated on-screen button/menu label the viewer must tap, or "" (keep it under 5 words).
- heading: 2-4 word summary of the step (e.g. "Open settings"), in {dst_name}.
"thumbnail_text": 2-5 punchy words for the video thumbnail in {dst_name} (e.g. "SEE ALL PASSWORDS").
Title (max 90 chars): {title}
Tags: {tags}
Scenes: {scenes}"""


def _via_llm(job: Job, scenes: list[dict], src: str, lang: str, engine: str) -> dict:
    """Groq or Gemini: natural translation + headings + thumbnail hook in one JSON answer."""
    payload = [{"id": s["id"], "text": s["text_src"], "callout": s["callout_src"]} for s in scenes]
    prompt = LLM_PROMPT.format(
        src_name=LANGUAGES.get(src, (src,))[0], dst_name=LANGUAGES.get(lang, (lang,))[0],
        title=job.data["title"], tags=json.dumps(job.data.get("tags", [])[:MAX_TAGS], ensure_ascii=False),
        scenes=json.dumps(payload, ensure_ascii=False),
    )
    res = (groq if engine == "groq" else gemini).generate_json(prompt)
    if not isinstance(res, dict):
        raise RuntimeError(f"{engine} returned a list instead of an object")
    by_id = {int(s["id"]): s for s in res.get("scenes", []) if isinstance(s, dict) and "id" in s}
    missing = [s["id"] for s in scenes if s["id"] not in by_id or not by_id[s["id"]].get("text")]
    if missing:
        raise RuntimeError(f"{engine} skipped scenes {missing[:10]}")
    built = [{"id": s["id"], "src": s["src"], "text": str(by_id[s["id"]]["text"]).strip(),
              "callout": str(by_id[s["id"]].get("callout") or ""),
              "heading": str(by_id[s["id"]].get("heading") or "")} for s in scenes]
    tap, step, intro = UI_LABELS.get(lang, (res.get("tap_label", "TAP"), res.get("step_label", "Step"), res.get("intro_label", "Intro")))
    return {"title": str(res.get("title") or job.data["title"]), "tags": [str(t) for t in res.get("tags", [])][:MAX_TAGS],
            "tap": tap, "intro": intro, "step": step, "thumb_text": str(res.get("thumbnail_text") or ""),
            "scenes": built, "engine": engine}


def _engines() -> list[str]:
    """LLM engines to try, in order, from the Settings choice."""
    choice = settings.load()["translator"]
    available = {"groq": groq.configured(), "gemini": gemini.configured()}
    if choice in ("groq", "gemini"):
        return [choice] if available[choice] else []
    if choice == "free":
        return []
    return [e for e in ("groq", "gemini") if available[e]]


def _via_free(job: Job, scenes: list[dict], src: str, lang: str) -> dict:
    tags = list(job.data.get("tags") or [])[:MAX_TAGS]
    texts = [job.data["title"], *(s["text_src"] for s in scenes), *(s["callout_src"] for s in scenes), *tags]
    done, engine = translate_texts(texts, src, lang)
    n = len(scenes)
    title = done[0]
    lines, callouts, tags_out = done[1:1 + n], done[1 + n:1 + 2 * n], done[1 + 2 * n:]
    tap, step, intro = UI_LABELS.get(lang, UI_LABELS["en"])
    built = [{"id": s["id"], "src": s["src"], "text": t, "callout": c, "heading": ""}
             for s, t, c in zip(scenes, lines, callouts)]
    return {"title": title, "tags": tags_out, "tap": tap, "intro": intro, "step": step, "scenes": built, "engine": engine}


HOOK_STOPWORDS = set("""
how to the a an of in on at for your you my all and or with from what why is are can do
cómo como que qué de del la las el los un una unos unas en con por para tu tus su sus todo todos toda todas y o
como o os as um uma do da dos das no na nos nas em com seu sua seus suas todos todas e ou
comment le les des du un une en au aux pour avec votre vos tout tous toute toutes et ou
wie der die das den dem ein eine im in am an zu mit für dein deine alle und oder
come il lo gli le un una di del della in con per tuo tua tutti tutte e o
""".split())


def short_hook(title: str, max_words: int = 3) -> str:
    """Fallback thumbnail text (no AI key): the first meaningful words of the translated title."""
    words = [w.strip(".,:;!?¿¡()|\"'") for w in title.split()]
    content = [w for w in words if w and w.lower() not in HOOK_STOPWORDS]
    return " ".join((content or words)[:max_words])


def with_chapters(scenes: list[dict], intro: str, step_word: str, title: str) -> list[dict]:
    """Intro until the first action; each action scene starts a new numbered step."""
    out, step = [], 0
    for sc in scenes:
        sc = {**sc, "callout": sc["callout"].strip().rstrip(".:;,!").strip()}  # button labels have no full stop
        if sc["callout"]:
            step += 1
        chapter = intro if step == 0 else f"{step_word} {step}"
        sub = title if step == 0 else sc.get("heading", "")
        out.append({**sc, "chapter": chapter, "sub": sub})
    return out


def run(job: Job) -> None:
    opts = job.data["options"]
    lang = opts["lang"]
    out = job.path("script", "scenes.json")
    if out.exists() and json.loads(out.read_text(encoding="utf8")).get("reviewed"):
        job.log("Translator", "script already reviewed by you — keeping it")
        return
    scenes = json.loads(job.path("script", "scenes_src.json").read_text(encoding="utf8"))
    src = (job.data.get("language") or "en").split("-")[0]
    result = None
    for engine in _engines():
        try:
            result = _via_llm(job, scenes, src, lang, engine)
            break
        except Exception as exc:
            job.log("Translator", f"{engine} failed ({str(exc)[:200]}) — trying the next engine")
    if result is None:
        if settings.load()["translator"] in ("groq", "gemini") and not _engines():
            job.log("Translator", f"no {settings.load()['translator']} key in Settings — using free translators")
        result = _via_free(job, scenes, src, lang)
    step_word = result.get("step") or "Step"
    spec = {
        "title": result["title"],
        "lang": lang,
        "voice": opts["voice"],
        "rate": opts.get("rate") or DEFAULT_RATE,
        "labels": {"tap": result["tap"].upper()[:12]},
        "tags": result["tags"],
        "engine": result["engine"],
        "thumb_text": (result.get("thumb_text") or short_hook(result["title"])).upper()[:60],
        "reviewed": False,
        "scenes": with_chapters(result["scenes"], result["intro"], step_word, result["title"]),
    }
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf8")
    job.log("Translator", f"{len(scenes)} lines translated to {LANGUAGES.get(lang, (lang,))[0]} via {result['engine']}")
