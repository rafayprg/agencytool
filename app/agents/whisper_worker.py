"""Transcribe a 16 kHz mono wav with faster-whisper (runs as a subprocess of the app).

Usage: whisper_worker.py <wav> <out.json> <model> <language|auto> [auto|cpu|gpu]
Writes {"language": str, "segments": [{start, end, text, words:[{w,s,e}]}]}.
Prints "PROGRESS <seconds>" lines so the app can show progress.
Pinned to ctranslate2 4.4 — newer builds crash on some Windows CPUs.
"""
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise ValueError("expected 16 kHz mono wav")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _add_cuda_dlls() -> None:
    """Windows: make the pip-installed NVIDIA libraries (setup-gpu.bat) visible to CTranslate2."""
    if os.name != "nt":
        return
    root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for bin_dir in root.glob("*/bin"):
        os.add_dll_directory(str(bin_dir))
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _gpu_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _transcribe(model_name: str, device: str, audio: np.ndarray, language: str):
    if device == "gpu":
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
    else:
        model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=max(2, (os.cpu_count() or 4) // 2))
    segments, info = model.transcribe(audio, word_timestamps=True, vad_filter=False,
                                      language=None if language == "auto" else language)
    return list(_iter(segments)), info


def _iter(segments):
    for s in segments:
        print(f"PROGRESS {s.end:.1f}", flush=True)
        yield s


def main() -> None:
    wav, out, model_name, language = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    wanted = sys.argv[5] if len(sys.argv) > 5 else "auto"
    _add_cuda_dlls()
    audio = load_wav(wav)
    device = "gpu" if wanted == "gpu" or (wanted == "auto" and _gpu_available()) else "cpu"
    try:
        segs, info = _transcribe(model_name, device, audio, language)
    except Exception as exc:
        if device != "gpu" or wanted == "gpu":
            raise
        print(f"DEVICE gpu failed ({str(exc)[:200]}) - using cpu", flush=True)
        device = "cpu"
        segs, info = _transcribe(model_name, device, audio, language)
    print(f"DEVICE {device}", flush=True)
    segments = segs
    rows = []
    for s in segments:
        rows.append({
            "start": round(s.start, 2),
            "end": round(s.end, 2),
            "text": s.text.strip(),
            "words": [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)} for w in (s.words or [])],
        })
    with open(out, "w", encoding="utf8") as f:
        json.dump({"language": info.language, "segments": rows}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
