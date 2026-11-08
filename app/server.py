"""Media Agency Studio — local web app. Run: python app/server.py  (http://127.0.0.1:8790)"""
import asyncio
import csv
import io
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_tts  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents import gemini, groq, library, notify, settings, siblings, styles  # noqa: E402
from agents.config import DATA, IMAGE_EXTS, JOBS, LANGUAGES, VIDEO_EXTS  # noqa: E402
from agents.crop import parse_crop  # noqa: E402
from agents.job import Job, all_jobs, valid_id  # noqa: E402
from worker import AGENTS, STAGE_NAMES, worker  # noqa: E402
from agents.autopilot import Autopilot, validate as validate_autopilot  # noqa: E402

autopilot = Autopilot(worker.enqueue)

PORT = int(os.environ.get("STUDIO_PORT", "8790"))
WEB = Path(__file__).resolve().parent / "web"
MAX_UPLOAD = 4 * 1024**3  # 4 GB
CHUNK = 1024 * 1024
RATE_RE = re.compile(r"^[+-][0-9]{1,2}%$")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("server")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    JOBS.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    added = await asyncio.to_thread(library.backfill)
    if added:
        log.info("library: remembered %d earlier projects", added)
    worker.start()
    worker.after_job = autopilot.nudge
    autopilot.start()
    if os.environ.get("STUDIO_OPEN_BROWSER") == "1":
        threading.Timer(1.0, webbrowser.open, args=[f"http://127.0.0.1:{PORT}"]).start()
    yield


app = FastAPI(title="Media Agency Studio", lifespan=lifespan)
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Only this PC's browser tab may use the studio: blocks other websites (CSRF) and DNS rebinding."""
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if host not in ALLOWED_HOSTS or (origin is not None and origin not in ALLOWED_ORIGINS):
        return JSONResponse({"detail": "requests are only accepted from the studio page itself"}, status_code=403)
    return await call_next(request)


def _job(job_id: str) -> Job:
    if not valid_id(job_id):
        raise HTTPException(404, "job not found")
    return Job.load(job_id)


def _files(job: Job) -> dict:
    base = f"/files/{job.id}"
    out = {}
    for key, rel in {
        "full_frame": "analysis/full_frame.jpg", "crop_preview": "analysis/crop_preview.jpg",
        "phone": "analysis/phone.mp4", "thumbnail": "source/video.webp",
        "video_16x9": "publish/final_16x9.mp4", "video_9x16": "publish/final_9x16.mp4",
        "thumb_new": "publish/thumbnail.jpg", "thumb_original": "publish/original_thumbnail.jpg",
        "captions": "publish/captions.srt", "metadata": "publish/metadata.json", "upload_txt": "publish/UPLOAD.txt",
    }.items():
        p = job.dir / rel
        if p.exists():
            out[key] = f"{base}/{rel}?v={int(p.stat().st_mtime)}"
    if "thumbnail" not in out:
        for ext in ("jpg", "png", "webp"):
            p = job.dir / "source" / f"video.{ext}"
            if p.exists():
                out["thumbnail"] = f"{base}/source/video.{ext}"
                break
    return out


def _summary(job: Job, full: bool = False) -> dict:
    d = job.data
    keys = ["status", "stage", "progress", "title", "error", "created", "updated", "options", "done",
            "duration", "width", "height", "crop", "language", "channel", "source", "cleaned", "exported_only", "siblings"]
    out = {"id": job.id, **{k: d.get(k) for k in keys}, "files": _files(job)}
    if full:
        out["log"] = d.get("log", [])
    return out


# ---------- meta ----------
@app.get("/api/meta")
async def meta() -> dict:
    return {
        "agents": [{"stage": a.stage, "name": a.name, "role": a.role} for a in AGENTS],
        "languages": [{"code": c, "name": n, "voice": v} for c, (n, v) in LANGUAGES.items()],
        "settings": settings.public(settings.load()),
    }


_voice_cache: list[dict] = []


def _voice_name(short_name: str) -> str:
    """'es-MX-JorgeNeural' -> 'Jorge', 'en-US-AvaMultilingualNeural' -> 'Ava (multilingual)'."""
    name = short_name.split("-", 2)[-1]
    multi = "Multilingual" in name
    name = name.replace("MultilingualNeural", "").replace("Neural", "")
    return f"{name} (multilingual)" if multi else name


@app.get("/api/voices")
async def voices(lang: str) -> list[dict]:
    global _voice_cache
    if not _voice_cache:
        try:
            _voice_cache = await edge_tts.list_voices()
        except Exception as exc:
            raise HTTPException(502, f"could not load voices (internet needed): {exc}") from exc
    return sorted(
        ({"id": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"],
          "name": _voice_name(v["ShortName"])}
         for v in _voice_cache if v["Locale"].split("-")[0] == lang),
        key=lambda v: (v["locale"], v["gender"], v["name"]),
    )


PREVIEW_TEXT = {
    "es": "Hola, así sonará la voz de tu video.", "pt": "Olá, esta é a voz do seu vídeo.",
    "fr": "Bonjour, voici la voix de votre vidéo.", "de": "Hallo, so klingt die Stimme deines Videos.",
    "it": "Ciao, questa è la voce del tuo video.", "hi": "नमस्ते, आपके वीडियो की आवाज़ ऐसी होगी।",
    "ur": "السلام علیکم، آپ کی ویڈیو کی آواز ایسی ہوگی۔", "ar": "مرحبا، هذا هو صوت الفيديو الخاص بك.",
    "tr": "Merhaba, videonun sesi böyle olacak.", "id": "Halo, beginilah suara video kamu.",
    "ru": "Привет, так будет звучать голос твоего видео.", "ja": "こんにちは、これがあなたの動画の声です。",
    "ko": "안녕하세요, 영상의 목소리는 이렇게 들립니다.", "zh": "你好，这是你视频的声音。",
    "en": "Hi, this is how the voice of your video will sound.",
}


@app.get("/api/voices/preview")
async def voice_preview(voice: str, rate: str = "+0%") -> FileResponse:
    if not all(c.isalnum() or c in "-" for c in voice) or not rate[:1] in "+-" or not rate[1:-1].isdigit():
        raise HTTPException(400, "bad voice or rate")
    cache = DATA / "voice_previews"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{voice}_{rate.replace('%', 'p').replace('+', 'u').replace('-', 'd')}.mp3"
    if not out.exists():
        text = PREVIEW_TEXT.get(voice.split("-")[0], PREVIEW_TEXT["en"])
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(str(out))
        except Exception as exc:
            out.unlink(missing_ok=True)
            raise HTTPException(502, f"voice preview failed: {exc}") from exc
    return FileResponse(out, media_type="audio/mpeg")


# ---------- styles ----------
@app.get("/api/styles")
async def list_styles() -> list[dict]:
    return styles.list_styles()


@app.post("/api/styles/reference")
async def style_from_reference(file: UploadFile = File(...), name: str = Form("")) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in IMAGE_EXTS | VIDEO_EXTS:
        raise HTTPException(400, "upload an image (png/jpg/webp) or a short video")
    ref_dir = DATA / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    dest = ref_dir / f"ref_{os.urandom(4).hex()}{ext}"
    await _save_upload(file, dest)
    try:
        return await asyncio.to_thread(styles.from_reference, dest, name.strip()[:40])
    except Exception as exc:
        raise HTTPException(400, f"could not read that reference: {exc}") from exc


class StyleIn(BaseModel):
    id: str
    name: str
    description: str = ""
    colors: dict
    font: str
    captionScale: float = 1
    layout: str = "phone-right"
    grid: bool = True
    music: bool = True
    musicVolume: float = 0.07


@app.put("/api/styles/{style_id}")
async def save_style(style_id: str, body: StyleIn) -> dict:
    try:
        return styles.save({**body.model_dump(), "id": style_id})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/styles/fonts")
async def fonts() -> dict:
    return styles.FONTS


# ---------- settings ----------
class SettingsIn(BaseModel):
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    translator: str | None = Field(default=None, pattern="^(auto|groq|gemini|free)$")
    mymemory_email: str | None = None
    whisper_model: str | None = Field(default=None, pattern="^(tiny|base|small|medium)$")
    default_lang: str | None = None
    default_voice: str | None = None
    default_style: str | None = None
    review_script: bool | None = None
    prep_ahead: int | None = Field(default=None, ge=0, le=10)
    transcribe_device: str | None = Field(default=None, pattern="^(auto|cpu|gpu)$")
    cleanup_after_done: bool | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=40)
    notify_done: bool | None = None
    notify_errors: bool | None = None
    library_dir: str | None = None


@app.put("/api/settings")
async def put_settings(body: SettingsIn) -> dict:
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if values.get("gemini_api_key", "").startswith("••••"):
        values.pop("gemini_api_key")
    new_key = values.get("gemini_api_key")
    if new_key:
        try:
            models = await asyncio.to_thread(gemini.list_models, new_key)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
        wanted = values.get("gemini_model") or settings.load()["gemini_model"]
        if models and wanted not in models:
            flash = [m for m in models if "flash" in m and "lite" not in m and "image" not in m and "tts" not in m]
            values["gemini_model"] = (flash or models)[-1]
    if values.get("groq_api_key", "").startswith("••••"):
        values.pop("groq_api_key")
    if values.get("telegram_bot_token", "").startswith("••••"):
        values.pop("telegram_bot_token")
    if "library_dir" in values:
        lib_dir = values["library_dir"].strip().strip('"')
        if lib_dir and not Path(lib_dir).is_dir():
            raise HTTPException(400, f"shared library folder not found: {lib_dir}")
        values["library_dir"] = lib_dir
    new_groq = values.get("groq_api_key")
    if new_groq:
        try:
            models = await asyncio.to_thread(groq.list_models, new_groq)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
        wanted = values.get("groq_model") or settings.load()["groq_model"]
        if models and wanted not in models:
            values["groq_model"] = groq.best_model(models)
    lang = values.get("default_lang")
    if lang:
        if lang not in LANGUAGES:
            raise HTTPException(400, "unknown language")
        current = settings.load()["default_voice"]
        if not current.startswith(lang + "-"):
            values["default_voice"] = LANGUAGES[lang][1]
    return settings.public(settings.save(values))


@app.post("/api/settings/telegram-test")
async def telegram_test(body: SettingsIn) -> dict:
    token = body.telegram_bot_token if body.telegram_bot_token and not body.telegram_bot_token.startswith("••••") else None
    try:
        await asyncio.to_thread(notify.send_now, "✅ Media Agency Studio is connected. You will get a message for every finished or failed video.",
                                token, (body.telegram_chat_id or "").strip() or None)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.post("/api/settings/groq-test")
async def groq_test(body: SettingsIn) -> dict:
    key = body.groq_api_key if body.groq_api_key and not body.groq_api_key.startswith("••••") else None
    try:
        models = await asyncio.to_thread(groq.list_models, key)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "models": models, "best": groq.best_model(models)}


@app.post("/api/settings/gemini-test")
async def gemini_test(body: SettingsIn) -> dict:
    key = body.gemini_api_key if body.gemini_api_key and not body.gemini_api_key.startswith("••••") else None
    try:
        models = await asyncio.to_thread(gemini.list_models, key)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "models": models}


# ---------- jobs ----------
async def _save_upload(file: UploadFile, dest: Path) -> None:
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "file is larger than 4 GB")
            f.write(chunk)


def _options(lang: str, voice: str, rate: str, style: str, formats: str, review: bool, crop_spec: str,
             allow_duplicate: bool = False) -> dict:
    if lang not in LANGUAGES:
        raise HTTPException(400, "unknown language")
    if voice.split("-")[0] != lang:
        raise HTTPException(400, "the voice does not match the language")
    if not RATE_RE.match(rate or "+6%"):
        raise HTTPException(400, "speed must look like +6% or -10%")
    if style and style not in {s["id"] for s in styles.list_styles()}:
        raise HTTPException(400, "unknown editing style")
    fmts = [f for f in formats.split(",") if f in ("16x9", "9x16")]
    if not fmts:
        raise HTTPException(400, "pick at least one format")
    if crop_spec.strip() and len(crop_spec.split(":")) != 4:
        raise HTTPException(400, "crop must be W:H:X:Y")
    return {"lang": lang, "voice": voice, "rate": rate or "+6%", "style": style or "neon-night",
            "formats": fmts, "review": review, "crop": crop_spec.strip(), "allow_duplicate": allow_duplicate}


@app.post("/api/jobs")
async def create_job(
    url: str = Form(""), lang: str = Form(...), voice: str = Form(...), rate: str = Form("+6%"),
    style: str = Form("neon-night"), formats: str = Form("16x9,9x16"), review: bool = Form(True),
    crop: str = Form(""), allow_duplicate: bool = Form(False), extra_langs: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict:
    options = _options(lang, voice, rate, style, formats, review, crop, allow_duplicate)
    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in VIDEO_EXTS:
            raise HTTPException(400, "upload a video file (mp4, mov, mkv, webm)")
        job = Job.create(options, {"kind": "file", "input": "", "title": Path(file.filename).stem})
        dest = job.path("source", f"upload{ext}")
        try:
            await _save_upload(file, dest)
        except HTTPException:
            shutil.rmtree(job.dir, ignore_errors=True)
            raise
        job.set(source={"kind": "file", "input": str(dest), "title": Path(file.filename).stem})
    elif url.strip().startswith(("http://", "https://")):
        job = Job.create(options, {"kind": "url", "input": url.strip()})
    else:
        raise HTTPException(400, "paste a YouTube / Google Drive link or upload a video")
    extra = [code for code in dict.fromkeys(extra_langs.split(",")) if code and code != lang]
    if any(code not in LANGUAGES for code in extra):
        raise HTTPException(400, "unknown extra language")
    worker.enqueue(job.id)
    for sib in siblings.create(job, extra):
        worker.enqueue(sib.id)
    return _summary(job)


@app.get("/api/jobs")
async def list_jobs() -> list[dict]:
    return [_summary(j) for j in all_jobs()]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    return _summary(_job(job_id), full=True)


@app.get("/api/jobs/{job_id}/script")
async def get_script(job_id: str) -> dict:
    job = _job(job_id)
    f = job.dir / "script" / "scenes.json"
    if not f.exists():
        raise HTTPException(404, "script not ready yet")
    spec = json.loads(f.read_text(encoding="utf8"))
    src_file = job.dir / "script" / "scenes_src.json"
    originals = {s["id"]: s["text_src"] for s in json.loads(src_file.read_text(encoding="utf8"))} if src_file.exists() else {}
    return {**spec, "scenes": [{**s, "original": originals.get(s["id"], "")} for s in spec["scenes"]]}


class SceneIn(BaseModel):
    id: int
    text: str = Field(min_length=1, max_length=1200)
    chapter: str = Field(default="", max_length=60)
    sub: str = Field(default="", max_length=120)
    callout: str = Field(default="", max_length=80)


class ScriptIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    thumb_text: str = Field(default="", max_length=60)
    tap_label: str = Field(default="TAP", max_length=12)
    tags: list[str] = []
    scenes: list[SceneIn]


@app.put("/api/jobs/{job_id}/script")
async def save_script(job_id: str, body: ScriptIn) -> dict:
    job = _job(job_id)
    f = job.dir / "script" / "scenes.json"
    if not f.exists():
        raise HTTPException(404, "script not ready yet")
    spec = json.loads(f.read_text(encoding="utf8"))
    edits = {s.id: s for s in body.scenes}
    scenes = [{**sc, **({"text": edits[sc["id"]].text.strip(), "chapter": edits[sc["id"]].chapter,
                         "sub": edits[sc["id"]].sub, "callout": edits[sc["id"]].callout} if sc["id"] in edits else {})}
              for sc in spec["scenes"]]
    spec = {**spec, "title": body.title, "thumb_text": body.thumb_text.strip() or spec.get("thumb_text", ""), "labels": {"tap": body.tap_label.upper()},
            "tags": [t.strip() for t in body.tags if t.strip()][:20], "scenes": scenes, "reviewed": True}
    f.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf8")
    job.log("Script Review", "script saved")
    return spec


class ContinueIn(BaseModel):
    from_stage: str | None = None
    voice: str | None = None
    rate: str | None = None
    style: str | None = None
    crop: str | None = None


@app.post("/api/jobs/{job_id}/run")
async def run_job(job_id: str, body: ContinueIn) -> dict:
    """Continue after review, retry after an error, or re-run from a stage with new options."""
    job = _job(job_id)
    if worker.is_busy(job_id) or job.data.get("status") == "running":
        raise HTTPException(409, "an agent is still working on this project — wait a moment and try again")
    opts = dict(job.data["options"])
    if body.voice:
        if body.voice.split("-")[0] != opts["lang"]:
            raise HTTPException(400, "the voice does not match the language")
        opts["voice"] = body.voice
    if body.rate:
        if not RATE_RE.match(body.rate):
            raise HTTPException(400, "speed must look like +6% or -10%")
        opts["rate"] = body.rate
    if body.style:
        if body.style not in {s["id"] for s in styles.list_styles()}:
            raise HTTPException(400, "unknown editing style")
        opts["style"] = body.style
    if body.crop is not None:
        if body.crop.strip() and job.data.get("width"):
            try:
                parse_crop(body.crop, job.data["width"], job.data["height"])
            except RuntimeError as exc:
                raise HTTPException(400, str(exc)) from exc
        opts["crop"] = body.crop.strip()
    start = body.from_stage
    if start and start not in STAGE_NAMES:
        raise HTTPException(400, "unknown stage")
    if start and job.data.get("cleaned") and start in ("crop", "voice", "render", "thumbnail"):
        raise HTTPException(409, "this project's working files were deleted by the disk saver — make it again from New video (tick 'make it again')")
    if start:
        # a new crop only changes the phone footage: skip transcription/translation/voice
        job.reset_from(["crop", "render", "thumbnail", "publish"] if start == "crop" else STAGE_NAMES[STAGE_NAMES.index(start):])
    if job.data.get("status") == "review" and not start:
        job.mark("review")
    if (body.voice or body.rate) and (job.dir / "script" / "scenes.json").exists():
        f = job.dir / "script" / "scenes.json"
        spec = json.loads(f.read_text(encoding="utf8"))
        f.write_text(json.dumps({**spec, "voice": opts["voice"], "rate": opts["rate"]}, ensure_ascii=False, indent=1), encoding="utf8")
    job.set(options=opts, status="queued", error="")
    worker.enqueue(job.id)
    return _summary(job)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    job = _job(job_id)
    job.set(status="cancelled")
    job.log("Orchestrator", "stopping…")
    return _summary(job)


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    job = _job(job_id)
    if worker.is_busy(job_id) or job.data.get("status") in ("running", "queued", "waiting"):
        raise HTTPException(409, "stop the project first (and wait for the current agent to finish)")
    shutil.rmtree(job.dir, ignore_errors=True)
    await asyncio.to_thread(library.report_status, job_id, "deleted")
    return {"deleted": job_id}


# ---------- autopilot (watched folder, 24/7) ----------
@app.get("/api/autopilot")
async def autopilot_status() -> dict:
    return await asyncio.to_thread(autopilot.status)


@app.put("/api/autopilot")
async def autopilot_config(body: dict) -> dict:
    current = autopilot.config()
    try:
        cfg = validate_autopilot({**current, **body, "enabled": current["enabled"]}, {s["id"] for s in styles.list_styles()})
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    autopilot.save_config(cfg)
    return await asyncio.to_thread(autopilot.status)


@app.post("/api/autopilot/{action}")
async def autopilot_action(action: str) -> dict:
    if action not in ("start", "stop", "scan"):
        raise HTTPException(404, "unknown action")
    try:
        if action in ("start", "stop"):
            autopilot.set_enabled(action == "start")
        autopilot.nudge()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return await asyncio.to_thread(autopilot.status)


# ---------- library (every video ever taken) ----------
@app.get("/api/library")
async def library_list(q: str = "", status: str = "") -> dict:
    rows = await asyncio.to_thread(library.entries)
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name"].lower() or ql in r["source"].lower()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"total": len(rows), "rows": rows[:500]}


@app.get("/api/library.csv")
async def library_csv() -> Response:
    rows = await asyncio.to_thread(library.entries)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "status", "project", "times_made", "source", "fingerprint", "first_seen", "last"])
    for r in rows:
        w.writerow([r["name"], r["status"], r["job"], r["times"], r["source"], r["fingerprint"],
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(r["first_seen"])),
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last"]))])
    return Response(chr(0xFEFF) + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="media-studio-library.csv"'})


JOBS.mkdir(exist_ok=True)
app.mount("/files", StaticFiles(directory=str(JOBS)), name="files")
app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
