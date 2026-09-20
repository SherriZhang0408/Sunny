from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry.pull import USER_AGENT, card_fetch_targets, fetch_sunny_card
from sunny_registry.probe import reject_url

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def _clone(name: str, agent_id: str = None, version: str = None) -> dict:
    card = _card(name)
    if agent_id:
        card["x-sunny"]["agent_id"] = agent_id
        card["name"] = agent_id
    if version:
        card["version"] = version
    return card


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "pull.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.developer_password = "dev-test-password"
    settings.seed_on_empty = False
    settings.pull_timeout_s = 0.5
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def _serve(card, path_suffix="/.well-known/agent-card.json"):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("user-agent") == USER_AGENT
        if request.url.path.endswith(path_suffix) or (
            path_suffix.endswith(".json") and request.url.path.endswith(path_suffix)
        ):
            return httpx.Response(200, json=card)
        return httpx.Response(404, json={"detail": "no"})

    return handler


def _install(client: TestClient, handler):
    client.app.state.store.settings.http_transport = httpx.MockTransport(handler)
    client.app.state.store.settings.pull_timeout_s = 0.5


def test_card_fetch_targets_order():
    assert card_fetch_targets("http://sidecar.test:8091") == [
        "http://sidecar.test:8091/.well-known/agent-card.json",
        "http://sidecar.test:8091/.well-known/agent.json",
    ]
    assert card_fetch_targets("http://sidecar.test:8091/.well-known/agent-card.json") == [
        "http://sidecar.test:8091/.well-known/agent-card.json"
    ]
    assert card_fetch_targets("http://sidecar.test/card.json") == ["http://sidecar.test/card.json"]


def test_reject_non_http_and_metadata_hosts():
    assert reject_url("file:///etc/passwd")
    assert reject_url("http://169.254.169.254/latest/meta-data")
    assert reject_url("http://metadata.google.internal/")
    assert reject_url("http://user:pass@10.0.0.1/card.json")


def test_pull_registers_from_well_known(client):
    card = _card("aidata.hermes.sample.json")
    _install(client, _serve(card))
    res = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["agent_id"] == "aidata.hermes"
    assert body["agent_key"].startswith("sak_")
    assert body["card_source_url"].endswith("/.well-known/agent-card.json")
    assert body["version"] == "0.1.0"
    detail = _admin(client, "get", "/api/v1/agents/aidata.hermes")
    assert detail.json()["card_source_url"] == body["card_source_url"]


def test_pull_falls_back_to_agent_json(client):
    card = _clone("lab.inspector.sample.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agent-card.json"):
            return httpx.Response(404)
        if request.url.path.endswith("/agent.json"):
            return httpx.Response(200, json=card)
        return httpx.Response(404)

    _install(client, handler)
    res = client.post(
        "/api/v1/agents/pull",
        json={"url": "http://sidecar.test:8091", "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["agent_id"] == "lab.inspector"
    assert res.json()["enrollment_source"] == "self"
    assert res.json()["card_source_url"].endswith("/.well-known/agent.json")


def test_pull_direct_json_url(client):
    card = _clone("lab.inspector.sample.json", "lab.direct")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/published.json":
            return httpx.Response(200, json=card)
        return httpx.Response(404)

    _install(client, handler)
    res = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://cards.test/published.json"})
    assert res.status_code == 200, res.text
    assert res.json()["agent_id"] == "lab.direct"


def test_pull_rejects_secret_card(client):
    card = _card("aidata.hermes.sample.json")
    card["password"] = "should-not-land"

    _install(client, _serve(card))
    res = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert res.status_code == 400
    assert "card rejected" in res.json()["detail"]
    listed = _admin(client, "get", "/api/v1/agents")
    assert listed.json()["count"] == 0


def test_pull_timeout(client):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    _install(client, handler)
    res = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert res.status_code == 502


def test_pull_blocks_file_and_metadata(client):
    file_res = _admin(client, "post", "/api/v1/agents/pull", json={"url": "file:///etc/passwd"})
    assert file_res.status_code == 400
    meta = _admin(
        client,
        "post",
        "/api/v1/agents/pull",
        json={"url": "http://169.254.169.254/latest/meta-data"},
    )
    assert meta.status_code == 400
    assert "blocked" in meta.json()["detail"] or "host" in meta.json()["detail"]


def test_pull_blocks_redirect_to_metadata(client):
    def handler(request: httpx.Request) -> httpx.Response:
        if "169.254" in request.url.host:
            return httpx.Response(200, json={"stolen": True})
        return httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
        )

    _install(client, handler)
    res = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert res.status_code == 400
    assert "blocked" in res.json()["detail"]


def test_enroll_cannot_overwrite_existing(client):
    card = _card("aidata.hermes.sample.json")
    _install(client, _serve(card))
    first = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert first.status_code == 200
    again = client.post(
        "/api/v1/agents/pull",
        json={"url": "http://sidecar.test:8091"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert again.status_code == 409
    assert "already registered" in again.json()["detail"]


def test_admin_pull_refreshes_and_stales_old_ticket(client):
    hermes = _card("aidata.hermes.sample.json")
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert inspector.status_code == 200
    _install(client, _serve(hermes))
    pulled = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert pulled.status_code == 200
    peer = {"X-Sunny-Agent-Key": inspector.json()["agent_key"]}
    callee = {"X-Sunny-Agent-Key": pulled.json()["agent_key"]}
    issued = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer,
    )
    assert issued.status_code == 200
    token = issued.json()["ticket"]
    bumped = _clone("aidata.hermes.sample.json", version="0.2.0")
    _install(client, _serve(bumped))
    refresh = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert refresh.status_code == 200
    assert "agent_key" not in refresh.json()
    assert refresh.json()["version"] == "0.2.0"
    stale = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=callee,
    )
    assert stale.status_code == 401
    assert "card version" in stale.json()["detail"]


def test_refresh_keeps_old_card_on_fetch_fail(client):
    card = _card("aidata.hermes.sample.json")
    _install(client, _serve(card))
    pulled = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert pulled.status_code == 200

    def down(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "nope"})

    _install(client, down)
    failed = _admin(client, "post", "/api/v1/agents/aidata.hermes/refresh")
    assert failed.status_code == 502
    still = _admin(client, "get", "/api/v1/agents/aidata.hermes")
    assert still.json()["version"] == "0.1.0"
    assert still.json()["name"] == card["name"]


def test_refresh_requires_source_url(client):
    created = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    assert created.status_code == 200
    res = _admin(client, "post", "/api/v1/agents/aidata.hermes/refresh")
    assert res.status_code == 400
    assert "card_source_url" in res.json()["detail"]


def test_refresh_forbidden_for_other_agent(client):
    _install(client, _serve(_card("aidata.hermes.sample.json")))
    _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    denied = client.post(
        "/api/v1/agents/aidata.hermes/refresh",
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert denied.status_code == 403


def test_admin_may_overlay_missing_agent_id(client):
    card = _card("lab.inspector.sample.json")
    del card["x-sunny"]["agent_id"]
    _install(client, _serve(card))
    missing = _admin(client, "post", "/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert missing.status_code == 400
    assert "agent_id" in missing.json()["detail"]
    filled = _admin(
        client,
        "post",
        "/api/v1/agents/pull",
        json={"url": "http://sidecar.test:8091", "agent_id": "lab.overlaid"},
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["agent_id"] == "lab.overlaid"


def test_non_admin_cannot_overlay_agent_id(client):
    card = _card("lab.inspector.sample.json")
    _install(client, _serve(card))
    res = client.post(
        "/api/v1/agents/pull",
        json={"url": "http://sidecar.test:8091", "agent_id": "lab.hijack"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert res.status_code == 403


def test_pull_requires_auth(client):
    res = client.post("/api/v1/agents/pull", json={"url": "http://sidecar.test:8091"})
    assert res.status_code == 401


def test_fetch_sunny_card_unit():
    card = {"name": "x"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agent-card.json"):
            return httpx.Response(200, json=card)
        return httpx.Response(404)

    fetched = fetch_sunny_card(
        "http://sidecar.test:8091",
        0.5,
        transport=httpx.MockTransport(handler),
    )
    assert fetched["card"] == card
    assert fetched["source_url"].endswith("/agent-card.json")
