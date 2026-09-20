from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry import security
from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def _owned_card(agent_id: str, name: str) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["name"] = name
    card["description"] = name + " 的说明"
    card["x-sunny"]["agent_id"] = agent_id
    return card


def _write_skill(skill_id: str = "lab.mutate") -> dict:
    return {
        "id": skill_id,
        "name": "内部写操作",
        "description": "仅管理员可签发的写副作用技能，不对对等开放。",
        "tags": ["internal", "write"],
        "examples": ["不要对对等签发"],
        "inputModes": ["application/json"],
        "outputModes": ["application/json"],
        "x-sunny": {
            "data_class": "restricted",
            "side_effects": "write",
            "invoke": {"method": "POST", "path": "/sunny/invoke/" + skill_id},
            "when_not_to_use": ["对等互调"],
            "input_schema": {"type": "object", "additionalProperties": True, "properties": {}},
            "output_schema": {"type": "object", "additionalProperties": True, "properties": {}},
        },
    }


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "security.db"
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
    _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat")
    return aidata, inspector


def test_enable_restores_peer_visibility_and_tickets(client):
    aidata, inspector = _register_pair(client)
    peer_headers = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    disabled = _admin(client, "post", "/api/v1/agents/aidata.hermes/disable")
    assert disabled.status_code == 200
    assert disabled.json()["lifecycle"] == "disabled"
    assert client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer_headers).json()["count"] == 0
    assert client.get("/api/v1/agents/aidata.hermes", headers=peer_headers).status_code == 404
    blocked = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer_headers,
    )
    assert blocked.status_code == 409

    enabled = _admin(client, "post", "/api/v1/agents/aidata.hermes/enable")
    assert enabled.status_code == 200
    assert enabled.json()["lifecycle"] == "registered"
    found = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer_headers)
    assert found.status_code == 200
    assert found.json()["count"] == 1
    assert client.get("/api/v1/agents/aidata.hermes", headers=peer_headers).status_code == 200
    ticket = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer_headers,
    )
    assert ticket.status_code == 200
    assert ticket.json()["caller_id"] == "lab.inspector"
    assert aidata["agent_id"] == "aidata.hermes"


def test_search_hides_write_skill_and_peer_cannot_ticket(client):
    _, inspector = _register_pair(client)
    patched = _admin(client, "patch", "/api/v1/agents/aidata.hermes", json={"add_skills": [_write_skill()]})
    assert patched.status_code == 200, patched.text
    skill_ids = {skill["id"] for skill in patched.json()["card"]["skills"]}
    assert "lab.mutate" in skill_ids

    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}
    hidden = client.get("/api/v1/search", params={"skill": "lab.mutate"}, headers=peer)
    assert hidden.status_code == 200
    assert hidden.json()["count"] == 0
    readable = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert readable.json()["count"] == 1

    denied = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "lab.mutate"},
        headers=peer,
    )
    assert denied.status_code == 403
    assert "write" in denied.json()["detail"]

    admin_ticket = _admin(
        client,
        "post",
        "/api/v1/tickets",
        json={"caller_id": "lab.inspector", "callee_id": "aidata.hermes", "skill_id": "lab.mutate"},
    )
    assert admin_ticket.status_code == 200, admin_ticket.text


def test_expired_and_tampered_ticket_rejected(client):
    aidata, inspector = _register_pair(client)
    callee_headers = {"X-Sunny-Agent-Key": aidata["agent_key"]}

    expired = security.issue_ticket(
        "ticket-test",
        "lab.inspector",
        "aidata.hermes",
        "collect.volume.query",
        -1,
    )
    stale = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": expired["ticket"], "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=callee_headers,
    )
    assert stale.status_code == 401
    assert "expired" in stale.json()["detail"]

    good = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert good.status_code == 200
    token = good.json()["ticket"]
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    bad = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": tampered, "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=callee_headers,
    )
    assert bad.status_code == 401
    assert "signature" in bad.json()["detail"]


def test_verify_rejects_mismatch_and_third_party(client):
    aidata, inspector = _register_pair(client)
    other = client.post(
        "/api/v1/agents",
        json={"card": _owned_card("lab.other", "第三方巡检"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    issued = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert issued.status_code == 200
    token = issued.json()["ticket"]
    callee = {"X-Sunny-Agent-Key": aidata["agent_key"]}

    wrong_callee = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "lab.inspector", "skill_id": "collect.volume.query"},
        headers=callee,
    )
    assert wrong_callee.status_code == 403
    assert "callee" in wrong_callee.json()["detail"]

    wrong_skill = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "aidata.hermes", "skill_id": "collect.strategy.query"},
        headers=callee,
    )
    assert wrong_skill.status_code == 403
    assert "skill" in wrong_skill.json()["detail"]

    stranger = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers={"X-Sunny-Agent-Key": other["agent_key"]},
    )
    assert stranger.status_code == 403
    assert "not for this agent" in stranger.json()["detail"]


def test_agent_ticket_ignores_spoofed_caller_id(client):
    _, inspector = _register_pair(client)
    issued = client.post(
        "/api/v1/tickets",
        json={
            "caller_id": "aidata.hermes",
            "callee_id": "aidata.hermes",
            "skill_id": "collect.volume.query",
        },
        headers={"X-Sunny-Agent-Key": inspector["agent_key"]},
    )
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert body["caller_id"] == "lab.inspector"
    payload = security.verify_ticket("ticket-test", body["ticket"])
    assert payload["caller"] == "lab.inspector"


def test_auth_helpers_reject_bad_identity():
    from fastapi import HTTPException

    assert security.bearer_from_header(None) is None
    assert security.bearer_from_header("Token abc") is None
    assert security.bearer_from_header("Bearer  sak_x ") == "sak_x"
    assert security.validate_username("Alice_1") == "Alice_1"
    with pytest.raises(HTTPException):
        security.validate_username("1admin")
    with pytest.raises(HTTPException):
        security.validate_password("123")
    with pytest.raises(HTTPException):
        security.validate_role("root")
    assert security.hash_password("secret-1") != "secret-1"
    assert security.verify_password("secret-1", security.hash_password("secret-1")) is True
    assert security.verify_password("nope", security.hash_password("secret-1")) is False


def test_expired_and_forged_session_rejected(client):
    expired = security.issue_session(
        "ticket-test",
        {"role": "developer", "user_id": "usr_developer", "username": "developer"},
        -1,
    )
    stale = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + expired["token"]})
    assert stale.status_code == 401
    assert "expired" in stale.json()["detail"]

    forged = security.issue_session(
        "wrong-secret",
        {"role": "admin", "user_id": "usr_admin", "username": "admin"},
        3600,
    )
    fake = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + forged["token"]})
    assert fake.status_code == 401
    assert client.get("/api/v1/agents", headers={"Authorization": "Bearer " + forged["token"]}).status_code == 401
