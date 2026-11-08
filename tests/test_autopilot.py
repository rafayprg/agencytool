"""Autopilot (watched folder) behaviour, with a fake folder and no worker."""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from agents import autopilot as ap  # noqa: E402
from agents import job as jobmod  # noqa: E402
from agents import library  # noqa: E402

STYLES = {"neon-night"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data, jobs, watch = tmp_path / "data", tmp_path / "jobs", tmp_path / "watch"
    for d in (data, jobs, watch):
        d.mkdir()
    monkeypatch.setattr(ap, "DATA", data)
    monkeypatch.setattr(ap, "CONFIG_FILE", data / "autopilot.json")
    monkeypatch.setattr(ap, "LEDGER_FILE", data / "autopilot_ledger.json")
    monkeypatch.setattr(jobmod, "JOBS", jobs)
    monkeypatch.setattr(library, "JOBS", jobs)
    monkeypatch.setattr(library, "DATA", data)
    monkeypatch.setattr(library, "LIBRARY_FILE", data / "library.json")
    queued: list[str] = []
    pilot = ap.Autopilot(queued.append)
    cfg = ap.validate({"watch_dir": str(watch), "min_age_sec": 10, "max_queue": 2, "enabled": True}, STYLES)
    pilot.save_config(cfg)
    return pilot, watch, queued


def make_video(folder: Path, name: str, age_sec: float = 120, content: bytes | None = None) -> Path:
    f = folder / name
    f.write_bytes(content if content is not None else name.encode() * 100)
    old = time.time() - age_sec
    os.utime(f, (old, old))
    return f


def test_partial_and_non_video_files_are_ignored(env):
    pilot, watch, queued = env
    make_video(watch, "a.mp4.part")
    make_video(watch, "b.f137.mp4")
    make_video(watch, "notes.txt")
    pilot.scan_once()
    pilot.scan_once()
    assert queued == []


def test_file_is_taken_only_once_it_is_stable_and_old_enough(env):
    pilot, watch, queued = env
    make_video(watch, "fresh.mp4", age_sec=0)
    make_video(watch, "done.mp4", age_sec=120)
    assert pilot.scan_once() == 0          # first look only records sizes
    assert pilot.scan_once() == 1          # stable now; "fresh" is still too new
    job = jobmod.Job.load(queued[0])
    assert job.data["source"]["input"].endswith("done.mp4")
    assert job.data["source"]["autopilot"] is True
    assert job.data["options"]["review"] is False


def test_max_queue_limits_projects_in_progress(env):
    pilot, watch, queued = env
    for i in range(5):
        make_video(watch, f"v{i}.mp4")
    pilot.scan_once()
    pilot.scan_once()
    assert len(queued) == 2
    pilot.scan_once()
    assert len(queued) == 2                # both still "queued": nothing more is taken
    for job_id in queued:
        jobmod.Job.load(job_id).set(status="done")
    pilot.scan_once()
    assert len(queued) == 4


def test_ledger_prevents_making_the_same_file_twice(env):
    pilot, watch, queued = env
    make_video(watch, "once.mp4")
    pilot.scan_once()
    pilot.scan_once()
    jobmod.Job.load(queued[0]).set(status="done")
    pilot.scan_once()
    pilot.scan_once()
    assert len(queued) == 1


def test_disabled_autopilot_does_nothing(env):
    pilot, watch, queued = env
    pilot.set_enabled(False)
    make_video(watch, "x.mp4")
    pilot.scan_once()
    pilot.scan_once()
    assert queued == []


def test_validate_rejects_bad_settings(tmp_path):
    with pytest.raises(ValueError):
        ap.validate({"watch_dir": str(tmp_path / "missing")}, STYLES)
    with pytest.raises(ValueError):
        ap.validate({"watch_dir": str(tmp_path), "output_dir": str(tmp_path)}, STYLES)
    with pytest.raises(ValueError):
        ap.validate({"lang": "es", "voice": "fr-FR-HenriNeural"}, STYLES)
    with pytest.raises(ValueError):
        ap.validate({"formats": []}, STYLES)


def test_failed_projects_are_retried_a_few_times(env):
    pilot, watch, queued = env
    make_video(watch, "net.mp4")
    pilot.scan_once()
    pilot.scan_once()
    job = jobmod.Job.load(queued[0])
    for attempt in range(1, ap.MAX_AUTO_RETRIES + 2):
        job.set(status="error")
        old = job.data["updated"] - ap.RETRY_AFTER_SEC - 1
        job.set(updated=old)
        job.data = {**job.data, "updated": old}
        job.save()
        pilot.scan_once()
        status = jobmod.Job.load(job.id).data["status"]
        assert status == ("queued" if attempt <= ap.MAX_AUTO_RETRIES else "error")


def test_same_video_under_two_names_is_made_once(env):
    pilot, watch, queued = env
    make_video(watch, "copy1.mp4", content=b"same-video" * 500)
    make_video(watch, "copy2.mp4", content=b"same-video" * 500)
    pilot.scan_once()
    pilot.scan_once()
    assert len(queued) == 1
    st = pilot.status()
    assert any(r.get("duplicate") for r in st["recent"])


def test_youtube_id_from_sidecar_marks_duplicates(env):
    pilot, watch, queued = env
    for name in ("a.mp4", "b.mp4"):
        make_video(watch, name)
        (watch / (name[0] + ".info.json")).write_text('{"id": "abcdefghijk", "extractor_key": "Youtube"}')
    pilot.scan_once()
    pilot.scan_once()
    assert len(queued) == 1
