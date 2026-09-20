from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry.probe import classify_probe, probe_card, reject_url

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "probe.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    settings.heartbeat_stale_s = 90
    settings.probe_timeout_s = 0.5
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def test_reject_non_http_and_metadata_hosts():
    assert reject_url("file:///etc/passwd")
    assert reject_url("http://169.254.169.254/latest/meta-data")
    assert reject_url("http://user:pass@10.0.0.1/health")
    assert reject_url("http://aidata.internal.example/sunny/v1") is None


def test_probe_card_hits_health_first():
    card = _card("aidata.hermes.sample.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": "no"})

    result = probe_card(card, 0.5, transport=httpx.MockTransport(handler))
    assert result["ok"] is True
    assert result["url"].endswith("/health")
    assert result["status_code"] == 200
    assert result["category"] == "OK"


def test_classify_probe_names_failures():
    assert classify_probe({"ok": True}) == "OK"
    assert classify_probe({"ok": False, "error": "url host is blocked"}) == "BLOCKED"
    assert classify_probe({"ok": False, "error": "timed out"}) == "TIMEOUT"
    assert classify_probe({"ok": False, "error": "SSL: CERTIFICATE_VERIFY_FAILED"}) == "TLS"
    assert classify_probe({"ok": False, "status_code": 404, "error": "http 404"}) == "404"
    assert classify_probe({"ok": False, "error": "connection refused"}) == "UNREACHABLE"


def test_search_hides_unknown_and_stale(client):
    hermes = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    assert hermes.status_code == 200
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    unseen = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert unseen.json()["count"] == 0

    assert _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat").status_code == 200
    live = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert live.json()["count"] == 1
    assert live.json()["items"][0]["runtime_status"] == "online"

    store = client.app.state.store
    row = store.get_row("aidata.hermes")
    store.conn.execute(
        "UPDATE agents SET last_heartbeat_at=? WHERE agent_id=?",
        ("2000-01-01T00:00:00Z", "aidata.hermes"),
    )
    store.conn.commit()
    assert store.runtime_status(store.get_row("aidata.hermes")) == "stale"

    stale = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert stale.json()["count"] == 0

    admin_hidden = _admin(client, "get", "/api/v1/search", params={"skill": "collect.volume.query"})
    assert admin_hidden.json()["count"] == 0
    admin_all = _admin(
        client,
        "get",
        "/api/v1/search",
        params={"skill": "collect.volume.query", "alive": "false"},
    )
    assert admin_all.json()["count"] == 1
    assert admin_all.json()["items"][0]["runtime_status"] == "stale"
    assert row["agent_id"] == "aidata.hermes"


def test_probe_endpoint_stores_signal(client):
    _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client.app.state.store.settings.probe_timeout_s = 0.5
    result = client.app.state.store.probe_agent(
        "aidata.hermes",
        "admin:admin",
        transport=httpx.MockTransport(handler),
    )
    assert result["probe"]["ok"] is True
    assert result["probe"]["checked_at"]
    assert result["probe"]["url"]

    via_api = _admin(client, "post", "/api/v1/agents/aidata.hermes/probe")
    assert via_api.status_code == 200
    assert "probe" in via_api.json()
    assert via_api.json()["probe"]["checked_at"]


def test_probe_forbidden_for_other_agent(client):
    _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    denied = client.post(
        "/api/v1/agents/aidata.hermes/probe",
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert denied.status_code == 403
