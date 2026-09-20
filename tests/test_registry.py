from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry.card_validate import validate_card

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "test.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    app = create_app(settings)
    return TestClient(app)


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def test_sample_cards_valid():
    assert validate_card(_card("aidata.hermes.sample.json")) == []
    assert validate_card(_card("lab.inspector.sample.json")) == []


def test_health(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_anonymous_cannot_list(client):
    res = client.get("/api/v1/agents")
    assert res.status_code == 401


def test_hub_register_and_search(client):
    card = _card("aidata.hermes.sample.json")
    res = _admin(client, "post", "/api/v1/agents", json={"card": card, "enrollment_source": "hub"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["agent_id"] == "aidata.hermes"
    assert body["enrollment_source"] == "hub"
    assert body["lifecycle"] == "registered"
    assert body["agent_key"].startswith("sak_")

    listed = _admin(client, "get", "/api/v1/agents").json()
    assert listed["count"] == 1

    beat = _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat")
    assert beat.status_code == 200
    found = _admin(client, "get", "/api/v1/search", params={"skill": "collect.volume.query"}).json()
    assert found["count"] == 1
    assert found["items"][0]["agent_id"] == "aidata.hermes"


def test_self_register_needs_enroll(client):
    card = _card("lab.inspector.sample.json")
    res = client.post("/api/v1/agents", json={"card": card, "enrollment_source": "self"})
    assert res.status_code == 401
    res = client.post(
        "/api/v1/agents",
        json={"card": card, "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert res.status_code == 200
    assert res.json()["enrollment_source"] == "self"


def test_secret_card_rejected(client):
    card = _card("lab.inspector.sample.json")
    card["api_token"] = "sk-this-is-long-enough-to-look-real"
    res = _admin(client, "post", "/api/v1/agents", json={"card": card, "enrollment_source": "hub"})
    assert res.status_code == 400
    assert "rejected" in res.json()["detail"]


def test_ticket_and_peer_discovery(client):
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
    assert _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat").status_code == 200

    peer = client.get(
        "/api/v1/search",
        params={"tag": "warehouse"},
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert peer.status_code == 200
    assert peer.json()["count"] == 1

    ticket = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert ticket.status_code == 200
    token = ticket.json()["ticket"]

    verify = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": aidata["agent_key"]},
    )
    assert verify.status_code == 200
    assert verify.json()["payload"]["caller"] == "lab.inspector"

    invoke = client.post(
        "/api/v1/invocations",
        json={
            "callee_id": "aidata.hermes",
            "skill_id": "collect.volume.query",
            "status": "ok",
            "trace_id": "t-1",
            "ticket": token,
        },
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert invoke.status_code == 200

    graph = _admin(client, "get", "/api/v1/graph").json()
    assert len(graph["nodes"]) == 2
    assert graph["edges"][0]["skill_id"] == "collect.volume.query"
    assert graph["edges"][0]["ticket_count"] >= 1


def test_disable_hides_from_search(client):
    _admin(client, "post", "/api/v1/agents", json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"})
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    _admin(client, "post", "/api/v1/agents/aidata.hermes/disable")
    found = client.get(
        "/api/v1/search",
        params={"skill": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    ).json()
    assert found["count"] == 0
    hidden = client.get(
        "/api/v1/agents/aidata.hermes",
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert hidden.status_code == 404


def test_admin_can_reissue_key(client):
    first = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    ).json()
    minted = _admin(client, "post", "/api/v1/agents/aidata.hermes/keys")
    assert minted.status_code == 200
    new_key = minted.json()["agent_key"]
    assert new_key.startswith("sak_")
    assert new_key != first["agent_key"]
    stale = client.post(
        "/api/v1/agents/aidata.hermes/heartbeat",
        headers={"X-Sunny-Agent-Key": first["agent_key"]},
    )
    assert stale.status_code == 401
    fresh = client.post(
        "/api/v1/agents/aidata.hermes/heartbeat",
        headers={"X-Sunny-Agent-Key": new_key},
    )
    assert fresh.status_code == 200


def test_revisions_recorded(client):
    _admin(client, "post", "/api/v1/agents", json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"})
    revs = _admin(client, "get", "/api/v1/agents/aidata.hermes/revisions").json()["items"]
    assert revs[0]["action"] == "create"
    snapshot = _admin(client, "get", "/api/v1/agents/aidata.hermes/revisions/{0}".format(revs[0]["rev"]))
    assert snapshot.status_code == 200
    assert snapshot.json()["card"]["x-sunny"]["agent_id"] == "aidata.hermes"
    missing = _admin(client, "get", "/api/v1/agents/aidata.hermes/revisions/999")
    assert missing.status_code == 404
    _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat")
    revs = _admin(client, "get", "/api/v1/agents/aidata.hermes/revisions").json()["items"]
    actions = [item["action"] for item in revs]
    assert "heartbeat" in actions


def test_invalid_enrollment_source_rejected(client):
    res = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "import"},
    )
    assert res.status_code == 400
    assert "enrollment_source" in res.json()["detail"]
