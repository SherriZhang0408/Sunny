from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry import policy, security
from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def _clone_card(agent_id: str, name: str, **sunny) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["name"] = name
    card["description"] = name + " 的说明"
    card["x-sunny"]["agent_id"] = agent_id
    card["x-sunny"].update(sunny)
    return card


def _restricted_read_skill(skill_id: str = "lab.secret.lookup") -> dict:
    return {
        "id": skill_id,
        "name": "受限只读",
        "description": "需 Extended Card，不对对等搜索开放。",
        "tags": ["internal", "restricted"],
        "examples": ["不要出现在对等搜索"],
        "inputModes": ["application/json"],
        "outputModes": ["application/json"],
        "x-sunny": {
            "data_class": "restricted",
            "side_effects": "read",
            "invoke": {"method": "POST", "path": "/sunny/invoke/" + skill_id},
            "when_not_to_use": ["对等发现"],
            "input_schema": {"type": "object", "additionalProperties": True, "properties": {}},
            "output_schema": {"type": "object", "additionalProperties": True, "properties": {}},
        },
    }


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "policy.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
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


def test_policy_helpers():
    assert policy.is_peer_visible("registered_peers") is True
    assert policy.is_peer_visible("private") is False
    assert policy.is_peer_visible("approval_required") is False
    assert policy.is_skill_searchable("internal", "read") is True
    assert policy.is_skill_searchable("public", "read") is True
    assert policy.is_skill_searchable("restricted", "read") is False
    assert policy.is_skill_searchable("internal", "write") is False
    assert policy.peer_ticket_denied({"data_class": "restricted", "side_effects": "read"}, "registered_peers")
    assert policy.ticket_version_stale("0.1.0", "0.2.0") is True
    assert policy.ticket_version_stale("0.1.0", "0.1.0") is False
    assert policy.ticket_version_stale(None, "0.1.0") is True


def test_search_hides_restricted_read_and_peer_cannot_ticket(client):
    _, inspector = _register_pair(client)
    patched = _admin(client, "patch", "/api/v1/agents/aidata.hermes", json={"add_skills": [_restricted_read_skill()]})
    assert patched.status_code == 200, patched.text
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    hidden = client.get("/api/v1/search", params={"skill": "lab.secret.lookup"}, headers=peer)
    assert hidden.status_code == 200
    assert hidden.json()["count"] == 0
    readable = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert readable.json()["count"] == 1

    denied = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "lab.secret.lookup"},
        headers=peer,
    )
    assert denied.status_code == 403
    assert "restricted" in denied.json()["detail"]

    admin_ticket = _admin(
        client,
        "post",
        "/api/v1/tickets",
        json={"caller_id": "lab.inspector", "callee_id": "aidata.hermes", "skill_id": "lab.secret.lookup"},
    )
    assert admin_ticket.status_code == 200, admin_ticket.text
    assert admin_ticket.json()["card_version"] == patched.json()["version"]


def test_private_and_approval_required_hidden_from_peers(client):
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
    private = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _clone_card("lab.private", "私有巡检", discovery="private"), "enrollment_source": "hub"},
    )
    assert private.status_code == 200, private.text
    pending = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _clone_card("lab.pending", "待审批巡检", discovery="approval_required"), "enrollment_source": "hub"},
    )
    assert pending.status_code == 200, pending.text

    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}
    listed = client.get("/api/v1/agents", headers=peer)
    assert listed.status_code == 200
    ids = {item["agent_id"] for item in listed.json()["items"]}
    assert "aidata.hermes" in ids
    assert "lab.inspector" in ids
    assert "lab.private" not in ids
    assert "lab.pending" not in ids

    assert client.get("/api/v1/search", params={"q": "私有"}, headers=peer).json()["count"] == 0
    assert client.get("/api/v1/agents/lab.private", headers=peer).status_code == 404
    assert client.get("/api/v1/agents/lab.pending", headers=peer).status_code == 404

    blocked = client.post(
        "/api/v1/tickets",
        json={"callee_id": "lab.private", "skill_id": "catalog.lookup"},
        headers=peer,
    )
    assert blocked.status_code == 403
    assert "not discoverable" in blocked.json()["detail"]

    admin_list = _admin(client, "get", "/api/v1/agents").json()
    admin_ids = {item["agent_id"] for item in admin_list["items"]}
    assert {"lab.private", "lab.pending"} <= admin_ids
    assert _admin(client, "get", "/api/v1/agents/lab.private").status_code == 200


def test_owner_still_sees_own_private_card(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "developer", "password": "dev-test-password"},
    )
    assert login.status_code == 200
    headers = {"Authorization": "Bearer " + login.json()["token"]}
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"card": _clone_card("dev.private", "开发者私有卡", discovery="private"), "enrollment_source": "hub"},
    )
    assert created.status_code == 200, created.text
    listed = client.get("/api/v1/agents", headers=headers)
    assert "dev.private" in {item["agent_id"] for item in listed.json()["items"]}
    detail = client.get("/api/v1/agents/dev.private", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["discovery"] == "private"


def test_ticket_binds_card_version_and_stales_on_bump(client):
    aidata, inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}
    callee = {"X-Sunny-Agent-Key": aidata["agent_key"]}

    issued = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer,
    )
    assert issued.status_code == 200
    assert issued.json()["card_version"] == "0.1.0"
    token = issued.json()["ticket"]
    payload = security.verify_ticket("ticket-test", token)
    assert payload["card_version"] == "0.1.0"

    fresh = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=callee,
    )
    assert fresh.status_code == 200

    bumped = _admin(client, "patch", "/api/v1/agents/aidata.hermes", json={"version": "0.1.1"})
    assert bumped.status_code == 200
    assert bumped.json()["version"] == "0.1.1"

    stale = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=callee,
    )
    assert stale.status_code == 401
    assert "card version" in stale.json()["detail"]

    replacement = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer,
    )
    assert replacement.status_code == 200
    assert replacement.json()["card_version"] == "0.1.1"


def test_legacy_ticket_without_version_rejected(client):
    aidata, _inspector = _register_pair(client)
    legacy = security.issue_ticket(
        "ticket-test",
        "lab.inspector",
        "aidata.hermes",
        "collect.volume.query",
        300,
    )
    assert "card_version" not in legacy["payload"]
    stale = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": legacy["ticket"], "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": aidata["agent_key"]},
    )
    assert stale.status_code == 401
    assert "card version" in stale.json()["detail"]
