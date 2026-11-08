"""Unit tests for the pure logic inside the agents (no network, no video files)."""
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from agents import crop, publish, scenes, styles, translate  # noqa: E402


def words(text: str, start: float = 0.0, step: float = 0.4) -> list[dict]:
    return [{"w": w, "s": round(start + i * step, 2), "e": round(start + i * step + 0.3, 2)} for i, w in enumerate(text.split())]


# ---------- scene planner ----------
def test_find_callout_extracts_capitalised_button_label():
    assert scenes.find_callout("Now tap on Manage your Google Account.") == "Manage your Google Account"
    assert scenes.find_callout("Then select Passwords from the menu") == "Passwords"


def test_find_callout_ignores_sentences_without_a_button():
    assert scenes.find_callout("I hope this video helps you out.") == ""
    assert scenes.find_callout("tap on it and you are done") == ""


def test_build_covers_the_whole_video_without_gaps():
    segs = [{"start": 0.5, "end": 6, "text": "", "words": words("Hello there. This is a tutorial about phones.", 0.5)},
            {"start": 7, "end": 12, "text": "", "words": words("Now tap on Settings to begin the process.", 7)}]
    result = scenes.build(segs, duration=20.0)
    assert result[0]["src"][0] == 0.0
    assert result[-1]["src"][1] == 20.0
    for a, b in zip(result, result[1:]):
        assert a["src"][1] == b["src"][0]
    assert any(s["callout_src"] == "Settings" for s in result)


def test_build_splits_long_monologue_into_scenes_of_max_length():
    long_text = " ".join(["word"] * 80)  # no punctuation, 32 s of speech
    result = scenes.build([{"start": 0, "end": 32, "text": long_text, "words": words(long_text)}], duration=33)
    assert len(result) >= 3


# ---------- translator ----------
def test_with_chapters_numbers_steps_on_callouts():
    raw = [{"id": 1, "callout": "", "heading": ""}, {"id": 2, "callout": "Ajustes", "heading": "Abre ajustes"},
           {"id": 3, "callout": "", "heading": ""}, {"id": 4, "callout": "Cuenta", "heading": ""}]
    out = translate.with_chapters(raw, "Intro", "Paso", "Título")
    assert [s["chapter"] for s in out] == ["Intro", "Paso 1", "Paso 1", "Paso 2"]
    assert out[0]["sub"] == "Título"
    assert out[1]["sub"] == "Abre ajustes"


def test_translate_texts_same_language_is_identity():
    texts, engine = translate.translate_texts(["a", "b"], "en", "en")
    assert texts == ["a", "b"] and engine == "none"


# ---------- phone cropper ----------
def _frame(tmp: Path, name: str, noise_seed: int) -> Path:
    rng = np.random.default_rng(noise_seed)
    img = rng.integers(40, 140, size=(540, 960, 3)).astype(np.uint8)  # busy, darker "room"
    img[30:500, 620:860] = 245  # bright portrait phone screen
    path = tmp / name
    Image.fromarray(img).save(path)
    return path


def test_detect_finds_bright_portrait_screen(tmp_path):
    frames = [_frame(tmp_path, f"f{i}.png", i) for i in range(5)]
    w, h, x, y = crop.detect(frames)
    assert abs(x - 620) <= 4 and abs(y - 30) <= 4
    assert abs(w - 240) <= 6 and abs(h - 470) <= 6


def test_detect_returns_none_without_phone(tmp_path):
    rng = np.random.default_rng(1)
    path = tmp_path / "x.png"
    Image.fromarray(rng.integers(0, 120, size=(540, 960, 3)).astype(np.uint8)).save(path)
    assert crop.detect([path]) is None


def test_parse_crop_validates_bounds():
    w, h, x, y = crop.parse_crop("461:1044:1235:18", 1920, 1080)
    assert (w % 2, h % 2) == (0, 0) and (x, y) == (1235, 18) and abs(w - 461) == 1
    with pytest.raises(RuntimeError):
        crop.parse_crop("500:1100:1500:0", 1920, 1080)
    with pytest.raises(RuntimeError):
        crop.parse_crop("abc", 1920, 1080)


# ---------- style designer ----------
def test_derive_colors_dark_reference_gives_dark_theme():
    pal = [((10, 14, 30), 5000), ((24, 37, 77), 3000), ((239, 198, 66), 400), ((54, 146, 226), 300), ((250, 250, 250), 200)]
    colors, dark = styles.derive_colors(pal)
    assert dark is True
    assert colors["text"] == "#ffffff"
    assert colors["accent"] != colors["accent2"]


def test_derive_colors_light_reference_gives_dark_text():
    pal = [((240, 238, 235), 9000), ((30, 120, 220), 500), ((220, 60, 50), 300)]
    colors, dark = styles.derive_colors(pal)
    assert dark is False and colors["text"] == "#101828"


def test_save_rejects_bad_colour(tmp_path, monkeypatch):
    monkeypatch.setattr(styles, "STYLES", tmp_path)
    good = {"id": "x-1", "name": "X", "colors": {k: "#000000" for k in styles.REQUIRED_COLORS}, "layout": "phone-right"}
    assert styles.save(good)["id"] == "x-1"
    with pytest.raises(ValueError):
        styles.save({**good, "colors": {**good["colors"], "accent": "red"}})
    with pytest.raises(ValueError):
        styles.save({**good, "id": "../evil"})


# ---------- publisher ----------
TIMELINE = {"fps": 30, "total": 900, "scenes": [
    {"from": 0, "chapter": "Intro", "callout": "", "words": [{"w": "Hola", "s": 0.1, "e": 0.5}]},
    {"from": 300, "chapter": "Paso 1", "callout": "Ajustes", "words": [{"w": "Toca", "s": 0.0, "e": 0.4}, {"w": "Ajustes", "s": 0.5, "e": 1.0}]},
    {"from": 600, "chapter": "Paso 1", "callout": "", "words": [{"w": "Listo", "s": 0.0, "e": 0.4}]},
]}


def test_chapters_start_at_zero_and_skip_repeats():
    assert publish.chapters(TIMELINE) == ["0:00 Intro", "0:10 Paso 1: Ajustes"]


def test_srt_has_timed_blocks():
    srt = publish.srt(TIMELINE)
    assert "00:00:00,100 --> 00:00:00,500\nHola" in srt
    assert "00:00:10,000 --> 00:00:11,000\nToca Ajustes" in srt


# ---------- job state ----------
def test_job_updates_from_two_objects_do_not_overwrite_each_other(tmp_path, monkeypatch):
    from agents import job as jobmod

    monkeypatch.setattr(jobmod, "JOBS", tmp_path)
    worker_side = jobmod.Job.create({"lang": "es"}, {"kind": "url", "input": "https://x"})
    api_side = jobmod.Job.load(worker_side.id)
    api_side.set(status="cancelled")          # user presses Stop
    worker_side.set(progress=0.5)             # worker still holds its old copy
    worker_side.log("Agent", "hello")
    final = jobmod.Job.load(worker_side.id).data
    assert final["status"] == "cancelled"
    assert final["progress"] == 0.5
    assert final["log"][-1]["msg"] == "hello"


def test_job_set_after_delete_raises(tmp_path, monkeypatch):
    import shutil

    from agents import job as jobmod

    monkeypatch.setattr(jobmod, "JOBS", tmp_path)
    j = jobmod.Job.create({}, {"kind": "url", "input": "https://x"})
    shutil.rmtree(j.dir)
    with pytest.raises(jobmod.JobDeleted):
        j.set(progress=1)
    assert not j.dir.exists()
