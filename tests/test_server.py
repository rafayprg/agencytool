"""API guard tests (no worker thread: the lifespan is not started)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import server  # noqa: E402

LOCAL = {"host": f"127.0.0.1:{server.PORT}"}


def client() -> TestClient:
    return TestClient(server.app)


def test_other_websites_are_blocked():
    r = client().post("/api/jobs", data={"url": "https://x"}, headers={**LOCAL, "origin": "https://evil.example"})
    assert r.status_code == 403


def test_dns_rebinding_host_is_blocked():
    assert client().get("/api/meta", headers={"host": "evil.example:8790"}).status_code == 403


def test_local_page_is_allowed():
    r = client().get("/api/meta", headers={**LOCAL, "origin": f"http://127.0.0.1:{server.PORT}"})
    assert r.status_code == 200
    assert "gemini_api_key" in r.json()["settings"]


def test_unknown_job_is_404_and_bad_ids_rejected():
    c = client()
    assert c.get("/api/jobs/nope-123", headers=LOCAL).status_code == 404
    assert c.get("/api/jobs/..%2F..%2Fdata", headers=LOCAL).status_code == 404


def test_create_job_validation():
    c = client()
    base = {"lang": "es", "voice": "es-MX-JorgeNeural"}
    assert c.post("/api/jobs", data={**base, "url": "x"}, headers=LOCAL).status_code == 400
    assert c.post("/api/jobs", data={**base, "url": "https://y", "voice": "fr-FR-HenriNeural"}, headers=LOCAL).status_code == 400
    assert c.post("/api/jobs", data={**base, "url": "https://y", "rate": "fast"}, headers=LOCAL).status_code == 400
    assert c.post("/api/jobs", data={**base, "url": "https://y", "style": "../x"}, headers=LOCAL).status_code == 400
