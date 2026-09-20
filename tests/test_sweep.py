from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def _clone(agent_id: str, version: str = None) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["x-sunny"]["agent_id"] = agent_id
    card["name"] = agent_id
    if version:
        card["version"] = version
    return card


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "sweep.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    settings.sweep_s = 0
    settings.refresh_interval_s = 0
    settings.probe_timeout_s = 0.5
    settings.pull_timeout_s = 0.5
    settings.heartbeat_stale_s = 90
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def test_health_advertises_sweep(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["sweep"]["interval_s"] == 0
    assert body["sweep"]["last"] is None


def test_s0_probe_ok_is_searchable_without_heartbeat(client):
    card = _card("aidata.hermes.sample.json")
    created = _admin(client, "post", "/api/v1/agents", json={"card": card, "enrollment_source": "hub"})
    assert created.status_code == 200, created.text
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    hidden = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert hidden.json()["count"] == 0

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    store = client.app.state.store
    store.settings.http_transport = httpx.MockTransport(handler)
    result = store.probe_agent("aidata.hermes", "admin:admin")
    assert result["runtime_status"] == "online"
    assert result["probe"]["ok"] is True
    assert result["probe"]["category"] == "OK"

    live = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert live.json()["count"] == 1
    assert live.json()["items"][0]["runtime_status"] == "online"


def test_s0_probe_timeout_hides_from_search(client):
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
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    store = client.app.state.store
    store.settings.http_transport = httpx.MockTransport(ok)
    store.probe_agent("aidata.hermes", "admin:admin")
    assert client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer).json()["count"] == 1

    store.settings.http_transport = httpx.MockTransport(boom)
    failed = store.probe_agent("aidata.hermes", "admin:admin")
    assert failed["runtime_status"] == "unreachable"
    assert failed["probe"]["category"] == "TIMEOUT"
    assert client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer).json()["count"] == 0

    admin_all = _admin(
        client,
        "get",
        "/api/v1/search",
        params={"skill": "collect.volume.query", "alive": "false"},
    )
    assert admin_all.json()["count"] == 1
    assert admin_all.json()["items"][0]["runtime_status"] == "unreachable"


def test_sweep_probes_and_refreshes_from_source(client):
    live = _clone("lab.sweep", "0.2.0")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/health") or path.endswith("/agent-card.json") or path.endswith("/agent.json"):
            return httpx.Response(200, json=live)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client.app.state.store.settings.http_transport = transport
    pulled = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert pulled.status_code == 200, pulled.text
    assert pulled.json()["agent_id"] == "lab.sweep"
    client.app.state.store.conn.execute(
        "UPDATE agents SET card_refreshed_at=NULL WHERE agent_id=?",
        ("lab.sweep",),
    )
    client.app.state.store.conn.commit()

    live["version"] = "0.3.0"
    live["description"] = "周期重抓后的说明"
    summary = client.app.state.store.sweep_once(transport=transport)
    assert summary["probed"] == 1
    assert summary["refreshed"] == 1
    assert summary["errors"] == 0

    detail = _admin(client, "get", "/api/v1/agents/lab.sweep")
    assert detail.json()["version"] == "0.3.0"
    assert detail.json()["probe"]["category"] == "OK"
    assert client.app.state.store.last_sweep["refreshed"] == 1


def test_sweep_refresh_failure_keeps_old_card(client):
    live = _clone("lab.keep", "1.0.0")

    def first(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".json") or request.url.path.endswith("/health"):
            return httpx.Response(200, json=live)
        return httpx.Response(404)

    client.app.state.store.settings.http_transport = httpx.MockTransport(first)
    pulled = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert pulled.status_code == 200, pulled.text
    client.app.state.store.conn.execute(
        "UPDATE agents SET card_refreshed_at=NULL WHERE agent_id=?",
        ("lab.keep",),
    )
    client.app.state.store.conn.commit()

    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    summary = client.app.state.store.sweep_once(transport=httpx.MockTransport(broken))
    assert summary["probed"] == 1
    assert summary["refreshed"] == 0
    assert summary["errors"] >= 1
    detail = _admin(client, "get", "/api/v1/agents/lab.keep")
    assert detail.json()["version"] == "1.0.0"
    assert detail.json()["runtime_status"] == "unreachable"
