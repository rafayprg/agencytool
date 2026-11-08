"""Paths and defaults shared by every agent."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
JOBS = ROOT / "jobs"
STUDIO = ROOT / "studio"
STYLES = ROOT / "styles"
DATA = ROOT / "data"            # settings.json, voice preview cache
PYTHON = Path(sys.executable)   # the app venv runs whisper too (subprocess, isolated memory)
CROP_PRESETS = ROOT / "crop_presets.json"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
FPS = 30
DEFAULT_RATE = "+6%"

# Target languages offered in the UI: code -> (name, default edge-tts voice)
LANGUAGES = {
    "es": ("Spanish", "es-MX-JorgeNeural"),
    "pt": ("Portuguese", "pt-BR-AntonioNeural"),
    "fr": ("French", "fr-FR-HenriNeural"),
    "de": ("German", "de-DE-ConradNeural"),
    "it": ("Italian", "it-IT-DiegoNeural"),
    "hi": ("Hindi", "hi-IN-MadhurNeural"),
    "ur": ("Urdu", "ur-PK-AsadNeural"),
    "ar": ("Arabic", "ar-SA-HamedNeural"),
    "tr": ("Turkish", "tr-TR-AhmetNeural"),
    "id": ("Indonesian", "id-ID-ArdiNeural"),
    "ru": ("Russian", "ru-RU-DmitryNeural"),
    "ja": ("Japanese", "ja-JP-KeitaNeural"),
    "ko": ("Korean", "ko-KR-InJoonNeural"),
    "zh": ("Chinese", "zh-CN-YunxiNeural"),
    "en": ("English", "en-US-AndrewNeural"),
}

# On-screen words that free translators get wrong on their own: (tap badge, step, intro)
UI_LABELS = {
    "es": ("TOCA", "Paso", "Introducción"), "pt": ("TOQUE", "Passo", "Introdução"),
    "fr": ("TOUCHE", "Étape", "Introduction"), "de": ("TIPPE", "Schritt", "Einführung"),
    "it": ("TOCCA", "Passo", "Introduzione"), "hi": ("टैप", "चरण", "परिचय"),
    "ur": ("ٹیپ", "مرحلہ", "تعارف"), "ar": ("انقر", "خطوة", "مقدمة"),
    "tr": ("DOKUN", "Adım", "Giriş"), "id": ("KETUK", "Langkah", "Pengantar"),
    "ru": ("НАЖМИ", "Шаг", "Введение"), "ja": ("タップ", "ステップ", "はじめに"),
    "ko": ("탭", "단계", "소개"), "zh": ("点击", "步骤", "简介"), "en": ("TAP", "Step", "Intro"),
}

# Assets every render needs, copied from studio/public into the job's render dir.
SHARED_ASSETS = ["bgm-tech-house.mp3", "pop.mp3", "swoosh-quick.mp3"]
