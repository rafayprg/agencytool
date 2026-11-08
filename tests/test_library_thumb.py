"""Library (duplicate memory), thumbnail key frame and hook text."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from agents import job as jobmod  # noqa: E402
from agents import library  # noqa: E402
from agents.thumbnail import key_frame_time  # noqa: E402
from agents.translate import short_hook  # noqa: E402


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(jobmod, "JOBS", jobs)
    monkeypatch.setattr(library, "JOBS", jobs)
    monkeypatch.setattr(library, "DATA", tmp_path)
    monkeypatch.setattr(library, "LIBRARY_FILE", tmp_path / "library.json")
    return tmp_path


def test_youtube_links_of_all_shapes_give_the_same_fingerprint():
    ids = {library.fingerprint(url=u) for u in (
        "https://www.youtube.com/watch?v=rje9RIuUxjI", "https://youtu.be/rje9RIuUxjI",
        "https://www.youtube.com/shorts/rje9RIuUxjI", "https://www.youtube.com/watch?list=x&v=rje9RIuUxjI")}
    assert ids == {"yt:rje9RIuUxjI"}


def test_same_bytes_same_hash_different_bytes_different_hash(tmp_path):
    a, b, c = tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"
    a.write_bytes(b"1" * 5_000_000)
    b.write_bytes(b"1" * 5_000_000)
    c.write_bytes(b"1" * 4_999_999 + b"2")
    assert library.fingerprint(a) == library.fingerprint(b)
    assert library.fingerprint(a) != library.fingerprint(c)


def test_owner_ignores_failed_and_deleted_projects(lib):
    done = jobmod.Job.create({}, {"kind": "url", "input": "x"})
    library.register("yt:abc", done.id, "v", "x")
    assert library.owner("yt:abc") == done.id
    done.set(status="error")
    assert library.owner("yt:abc") is None          # a failed attempt may be made again
    done.set(status="done")
    assert library.owner("yt:abc", exclude_job=done.id) is None
    assert library.entries()[0]["status"] == "done"


def test_key_frame_prefers_the_scene_matching_the_title():
    scenes = [
        {"callout": "Google Chrome", "text": "Abre Chrome", "src": [0, 10]},
        {"callout": "Administrador de contraseñas", "text": "Toca el administrador", "src": [50, 60]},
        {"callout": "Perfil", "text": "Toca tu perfil", "src": [20, 30]},
    ]
    t = key_frame_time(scenes, 100, "Cómo ver todas las contraseñas guardadas")
    assert 50 <= t <= 60


def test_short_hook_drops_filler_words():
    assert short_hook("Cómo ver todas las contraseñas guardadas en la cuenta de Google") == "ver contraseñas guardadas"
    assert short_hook("How To See All Saved Password In Google Account") == "See Saved Password"
