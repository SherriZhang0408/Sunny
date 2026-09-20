from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.a2a_export import has_restricted_skills, public_card, strip_sunny_extensions
from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "extended.db"
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
    hermes = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    assert hermes.status_code == 200, hermes.text
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert inspector.status_code == 200, inspector.text
    _admin(client, "post", "/api/v1/agents/lab.inspector/heartbeat")
    return hermes.json(), inspector.json()


def test_public_card_strips_restricted_and_keeps_x_sunny():
    card = _card("lab.inspector.sample.json")
    assert has_restricted_skills(card)
    public = public_card(card)
    ids = [skill["id"] for skill in public["skills"]]
    assert "catalog.lookup" in ids
    assert "lab.secret.lookup" not in ids
    assert public["capabilities"]["extendedAgentCard"] is True
    assert "x-sunny" in json.dumps(public)
    exported = strip_sunny_extensions(public)
    assert "x-sunny" not in json.dumps(exported)
    assert "lab.secret.lookup" not in json.dumps(exported)


def test_peer_gets_public_card_and_extended_has_restricted(client):
    _, inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    public = client.get("/api/v1/agents/lab.inspector", headers=peer)
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["card_view"] == "full"
    assert body["has_extended"] is True
    ids = [skill["id"] for skill in body["card"]["skills"]]
    assert "lab.secret.lookup" in ids

    hermes_public = client.get("/api/v1/agents/aidata.hermes", headers=peer)
    assert hermes_public.status_code == 200
    assert hermes_public.json()["card_view"] == "public"
    assert "lab.secret.lookup" not in json.dumps(hermes_public.json()["card"])

    listed = client.get("/api/v1/agents", headers=peer)
    inspector_row = [item for item in listed.json()["items"] if item["agent_id"] == "lab.inspector"][0]
    assert inspector_row["card_view"] == "full"
    hermes_row = [item for item in listed.json()["items"] if item["agent_id"] == "aidata.hermes"][0]
    assert hermes_row["card_view"] == "public"

    patched = _admin(
        client,
        "patch",
        "/api/v1/agents/aidata.hermes",
        json={
            "add_skills": [
                {
                    "id": "hermes.secret.lookup",
                    "name": "Hermes 受限",
                    "description": "只给 Extended Card。",
                    "tags": ["restricted"],
                    "x-sunny": {
                        "data_class": "restricted",
                        "side_effects": "read",
                        "invoke": {"method": "POST", "path": "/sunny/invoke/hermes.secret.lookup"},
                        "when_not_to_use": [],
                        "input_schema": {"type": "object", "additionalProperties": True, "properties": {}},
                        "output_schema": {"type": "object", "additionalProperties": True, "properties": {}},
                    },
                }
            ]
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["card"]["capabilities"]["extendedAgentCard"] is True

    peer_hermes = client.get("/api/v1/agents/aidata.hermes", headers=peer)
    assert peer_hermes.status_code == 200
    peer_ids = [skill["id"] for skill in peer_hermes.json()["card"]["skills"]]
    assert "hermes.secret.lookup" not in peer_ids
    assert "collect.volume.query" in peer_ids
    assert peer_hermes.json()["card_view"] == "public"
    assert peer_hermes.json()["has_extended"] is True
    assert peer_hermes.json()["card"]["capabilities"]["extendedAgentCard"] is True

    extended = client.get("/api/v1/agents/aidata.hermes/extended", headers=peer)
    assert extended.status_code == 200, extended.text
    ext_ids = [skill["id"] for skill in extended.json()["card"]["skills"]]
    assert "hermes.secret.lookup" in ext_ids
    assert extended.json()["card_view"] == "full"
    assert extended.headers.get("etag") == '"0.1.0"'
    assert extended.headers.get("vary") == "Authorization"
    assert "private" in (extended.headers.get("cache-control") or "")

    cached = client.get(
        "/api/v1/agents/aidata.hermes/extended",
        headers=dict(peer, **{"If-None-Match": '"0.1.0"'}),
    )
    assert cached.status_code == 304

    a2a = client.get("/api/v1/agents/aidata.hermes/a2a", headers=peer)
    assert a2a.status_code == 200
    dumped = json.dumps(a2a.json())
    assert "hermes.secret.lookup" not in dumped
    assert "x-sunny" not in dumped

    denied = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "hermes.secret.lookup"},
        headers=peer,
    )
    assert denied.status_code == 403
    assert "restricted" in denied.json()["detail"]

    admin_ticket = _admin(
        client,
        "post",
        "/api/v1/tickets",
        json={
            "caller_id": "lab.inspector",
            "callee_id": "aidata.hermes",
            "skill_id": "hermes.secret.lookup",
        },
    )
    assert admin_ticket.status_code == 200, admin_ticket.text


def test_developer_reads_public_card_admin_keeps_full(client):
    _register_pair(client)
    _admin(
        client,
        "patch",
        "/api/v1/agents/aidata.hermes",
        json={
            "add_skills": [
                {
                    "id": "hermes.secret.lookup",
                    "name": "Hermes 受限",
                    "description": "只给 Extended Card。",
                    "tags": ["restricted"],
                    "x-sunny": {
                        "data_class": "restricted",
                        "side_effects": "read",
                        "invoke": {"method": "POST", "path": "/sunny/invoke/hermes.secret.lookup"},
                        "when_not_to_use": [],
                        "input_schema": {"type": "object", "additionalProperties": True, "properties": {}},
                        "output_schema": {"type": "object", "additionalProperties": True, "properties": {}},
                    },
                }
            ]
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "developer", "password": "dev-test-password"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["token"]}

    public = client.get("/api/v1/agents/aidata.hermes", headers=headers)
    assert public.status_code == 200
    assert public.json()["card_view"] == "public"
    assert "hermes.secret.lookup" not in json.dumps(public.json()["card"])

    extended = client.get("/api/v1/agents/aidata.hermes/extended", headers=headers)
    assert extended.status_code == 200
    assert "hermes.secret.lookup" in json.dumps(extended.json()["card"])

    admin = _admin(client, "get", "/api/v1/agents/aidata.hermes")
    assert admin.json()["card_view"] == "full"
    assert "hermes.secret.lookup" in json.dumps(admin.json()["card"])


def test_anonymous_cannot_read_extended(client):
    _register_pair(client)
    assert client.get("/api/v1/agents/lab.inspector/extended").status_code == 401
    assert client.get("/api/v1/agents/lab.inspector").status_code == 401
