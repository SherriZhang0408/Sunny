from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "observe.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def _register_pair(client: TestClient):
    aidata = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    ).json()
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    return aidata, inspector


def test_search_ticket_invoke_share_timeline(client):
    aidata, inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    search = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert search.status_code == 200
    assert search.json()["count"] == 1

    ticket = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer,
    )
    assert ticket.status_code == 200
    token = ticket.json()["ticket"]
    jti = ticket.json()["jti"]

    invoke = client.post(
        "/api/v1/invocations",
        json={
            "callee_id": "aidata.hermes",
            "skill_id": "collect.volume.query",
            "status": "ok",
            "trace_id": "obs-trace-1",
            "ticket": token,
        },
        headers=peer,
    )
    assert invoke.status_code == 200

    timeline = _admin(client, "get", "/api/v1/activity").json()["items"]
    kinds = [item["kind"] for item in timeline]
    assert kinds.count("search") >= 1
    assert kinds.count("ticket") >= 1
    assert kinds.count("invoke") >= 1
    assert kinds.count("card") >= 1

    blob = json.dumps(timeline)
    assert token not in blob
    assert "sak_" not in blob

    by_trace = _admin(client, "get", "/api/v1/activity", params={"trace_id": "obs-trace-1"}).json()
    assert by_trace["count"] >= 1
    assert all(item["kind"] == "invoke" for item in by_trace["items"])
    assert by_trace["items"][0]["trace_id"] == "obs-trace-1"
    assert by_trace["items"][0]["ticket_jti"] == jti

    searches = _admin(client, "get", "/api/v1/activity", params={"kind": "search"}).json()["items"]
    assert searches[0]["detail"]["hits"] == ["aidata.hermes"]
    assert searches[0]["detail"]["skill"] == "collect.volume.query"
    assert searches[0]["caller_id"] == "lab.inspector"
    assert aidata["agent_id"] == "aidata.hermes"


def test_denied_ticket_is_recorded(client):
    _admin(client, "post", "/api/v1/agents", json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"})
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    _admin(client, "post", "/api/v1/agents/aidata.hermes/disable")
    blocked = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert blocked.status_code == 409
    tickets = _admin(client, "get", "/api/v1/activity", params={"kind": "ticket"}).json()["items"]
    assert tickets[0]["status"] == "denied"
    assert "not registered" in tickets[0]["detail"]["reason"]


def test_activity_rejects_unknown_kind(client):
    res = _admin(client, "get", "/api/v1/activity", params={"kind": "explode"})
    assert res.status_code == 400
