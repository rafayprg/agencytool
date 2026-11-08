"""Pipeline lanes, two-PC library claims, language siblings, disk saver and disk guard."""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from agents import autopilot as ap  # noqa: E402
from agents import ingest, library, publish  # noqa: E402
from agents import job as jobmod  # noqa: E402
from agents import settings as settingsmod  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    jobs, data = tmp_path / "jobs", tmp_path / "data"
    jobs.mkdir()
    data.mkdir()
    for mod in (jobmod, library, ingest, publish):
        monkeypatch.setattr(mod, "JOBS", jobs, raising=False)
    monkeypatch.setattr(ap, "JOBS", jobs)
    monkeypatch.setattr(library, "LIBRARY_FILE", data / "library.json")
    monkeypatch.setattr(ap, "DATA", data)
    monkeypatch.setattr(ap, "CONFIG_FILE", data / "autopilot.json")
    monkeypatch.setattr(ap, "LEDGER_FILE", data / "autopilot_ledger.json")
    return tmp_path


def make_job(lang="es", **data):
    job = jobmod.Job.create({"lang": lang, "voice": f"{lang}-X-Neural"}, {"kind": "url", "input": "x"})
    if data:
        job.set(**data)
    return job


# ---------- two PCs sharing one library ----------
def test_claim_is_refused_while_the_other_pc_is_making_the_video(env):
    import json

    k = library.key("yt:abc", "es")
    library.LIBRARY_FILE.write_text(json.dumps({k: {"jobs": [{"id": "jOther", "pc": "OTHER-PC", "status": "running"}]}}))
    mine = make_job()
    assert library.claim(k, mine.id, "v", "x") == "jOther on OTHER-PC"
    # the other PC reports that its attempt failed -> this PC may take the video
    data = json.loads(library.LIBRARY_FILE.read_text())
    data[k]["jobs"][0]["status"] = "error"
    library.LIBRARY_FILE.write_text(json.dumps(data))
    assert library.claim(k, mine.id, "v", "x") is None
    assert library.owner(k) == mine.id


def test_same_video_other_language_is_allowed(env):
    a, b = make_job("es"), make_job("pt")
    assert library.claim(library.key("yt:abc", "es"), a.id, "v", "x") is None
    assert library.claim(library.key("yt:abc", "pt"), b.id, "v", "x") is None
    assert library.claim(library.key("yt:abc", "es"), b.id, "v", "x") == a.id


def test_stale_lock_from_a_crashed_pc_is_ignored(env):
    lock = library.LIBRARY_FILE.with_suffix(".lock")
    lock.write_text("CRASHED-PC")
    old = time.time() - library.LOCK_STALE_SEC - 5
    os.utime(lock, (old, old))
    assert library.claim(library.key("yt:zz", "es"), make_job().id, "v", "x") is None
    assert not lock.exists()


# ---------- language siblings ----------
def _main_with_files(env) -> jobmod.Job:
    main = make_job("es", video="source/video.mp4", duration=30.0, width=1920, height=1080, title="T",
                    crop={"w": 400, "h": 800, "x": 0, "y": 0}, fingerprint="yt:main0000001", language="en")
    for rel in ("source/video.mp4", "analysis/phone.mp4", "analysis/transcript.json", "script/scenes_src.json"):
        main.path(rel).write_bytes(b"data-" + rel.encode())
    return main


def test_sibling_waits_until_main_has_its_transcript(env):
    main = _main_with_files(env)
    sib = jobmod.Job.create({"lang": "pt", "voice": "pt-BR-X"}, {"kind": "sibling", "input": main.id})
    with pytest.raises(ingest.WaitForMain):
        ingest._from_main(sib)


def test_sibling_reuses_main_files_and_skips_its_stages(env):
    main = _main_with_files(env)
    for stage in ("ingest", "crop", "transcribe", "scenes"):
        main.mark(stage)
    sib = jobmod.Job.create({"lang": "pt", "voice": "pt-BR-X"}, {"kind": "sibling", "input": main.id})
    ingest._from_main(sib)
    sib = jobmod.Job.load(sib.id)
    assert (sib.dir / "analysis" / "phone.mp4").read_bytes() == b"data-analysis/phone.mp4"
    assert {"crop", "transcribe", "scenes"} <= set(sib.data["done"])
    assert sib.data["crop"]["w"] == 400 and sib.data["options"]["lang"] == "pt"
    assert library.owner(library.key("yt:main0000001", "pt")) == sib.id


# ---------- autopilot: languages + disk guard ----------
def _autopilot(env, **cfg):
    watch = env / "watch"
    watch.mkdir(exist_ok=True)
    queued: list[str] = []
    pilot = ap.Autopilot(queued.append)
    pilot.save_config(ap.validate({"watch_dir": str(watch), "min_age_sec": 10, "max_queue": 6, "enabled": True, **cfg},
                                  {"neon-night"}))
    f = watch / "v.mp4"
    f.write_bytes(b"video-bytes" * 300)
    old = time.time() - 120
    os.utime(f, (old, old))
    return pilot, queued


def test_autopilot_makes_main_plus_language_siblings(env):
    pilot, queued = _autopilot(env, extra_langs=["pt", "hi"])
    pilot.scan_once()
    pilot.scan_once()
    langs = sorted(jobmod.Job.load(j).data["options"]["lang"] for j in queued)
    kinds = sorted(jobmod.Job.load(j).data["source"]["kind"] for j in queued)
    assert langs == ["es", "hi", "pt"]
    assert kinds == ["sibling", "sibling", "watch"]
    pilot.scan_once()
    assert len(queued) == 3  # nothing is made twice


def test_autopilot_pauses_when_the_disk_is_almost_full(env, monkeypatch):
    pilot, queued = _autopilot(env, min_free_gb=50)
    monkeypatch.setattr(ap.shutil, "disk_usage", lambda _p: type("U", (), {"free": 3 * 1024**3})())
    pilot.scan_once()
    pilot.scan_once()
    assert queued == []
    assert "paused" in pilot.state["last_error"]


# ---------- disk saver ----------
def test_cleanup_keeps_the_package_and_spares_files_a_sibling_still_needs(env):
    main = _main_with_files(env)
    main.path("publish/final_9x16.mp4").write_bytes(b"x" * 100)
    main.path("render/public/vo/a.mp3").write_bytes(b"x" * 50)
    sib = jobmod.Job.create({"lang": "pt"}, {"kind": "sibling", "input": main.id})
    main.set(siblings=[sib.id])
    publish.cleanup(jobmod.Job.load(main.id))
    assert (main.dir / "publish" / "final_9x16.mp4").exists()
    assert not (main.dir / "render" / "public").exists()
    assert (main.dir / "analysis" / "phone.mp4").exists()     # sibling has not copied it yet
    sib.mark("ingest")
    publish.cleanup(jobmod.Job.load(main.id), keep_publish_videos=False)
    assert not (main.dir / "analysis" / "phone.mp4").exists()
    assert not (main.dir / "publish" / "final_9x16.mp4").exists()
    assert jobmod.Job.load(main.id).data["cleaned"] is True


# ---------- pipeline lanes ----------
def test_jobs_go_to_the_lane_that_owns_their_next_stage(env, monkeypatch):
    import worker as workermod

    monkeypatch.setattr(workermod, "JOBS", env / "jobs")
    w = workermod.Worker()
    fresh = make_job()
    prepared = make_job()
    for stage in workermod.PREP_STAGES:
        prepared.mark(stage)
    w.enqueue(fresh.id)
    w.enqueue(prepared.id)
    assert w.prep.queued == {fresh.id}
    assert w.editor.queued == {prepared.id}


def test_prep_lane_stops_preparing_when_enough_videos_wait(env, monkeypatch):
    import worker as workermod

    w = workermod.Worker()
    monkeypatch.setattr(settingsmod, "load", lambda: {**settingsmod.DEFAULTS, "prep_ahead": 2})
    assert w._prep_may_start()
    w.editor.queued = {"a", "b"}
    assert not w._prep_may_start()
    monkeypatch.setattr(settingsmod, "load", lambda: {**settingsmod.DEFAULTS, "prep_ahead": 0})
    w.editor.queued = set()
    w.editor.current_id = "rendering"
    assert not w._prep_may_start()  # 0 = strictly one video at a time
