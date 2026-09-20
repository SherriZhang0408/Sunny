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
    settings.db_path = tmp_path / "deprecated.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    settings.heartbeat_stale_s = 90
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
    assert _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat").status_code == 200
    return hermes.json(), inspector.json()


def test_deprecated_readable_but_no_new_ticket(client):
    _aidata, inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    issued = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer,
    )
    assert issued.status_code == 200, issued.text
    old_ticket = issued.json()["ticket"]

    deprecated = _admin(client, "post", "/api/v1/agents/aidata.hermes/deprecate")
    assert deprecated.status_code == 200
    assert deprecated.json()["lifecycle"] == "deprecated"

    shown = client.get("/api/v1/agents/aidata.hermes", headers=peer)
    assert shown.status_code == 200
    assert shown.json()["lifecycle"] == "deprecated"

    found = client.get("/api/v1/search", params={"skill": "collect.volume.query"}, headers=peer)
    assert [item["agent_id"] for item in found.json()["items"]] == ["aidata.hermes"]

    blocked = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "callee is deprecated"

    admin_blocked = _admin(
        client,
        "post",
        "/api/v1/tickets",
        json={"caller_id": "lab.inspector", "callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
    )
    assert admin_blocked.status_code == 409

    verified = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": old_ticket, "callee_id": "aidata.hermes"},
        headers=peer,
    )
    assert verified.status_code == 200

    enabled = _admin(client, "post", "/api/v1/agents/aidata.hermes/enable")
    assert enabled.json()["lifecycle"] == "registered"
    fresh = client.post(
        "/api/v1/tickets",
        json={"callee_id": "aidata.hermes", "skill_id": "collect.volume.query"},
        headers=peer,
    )
    assert fresh.status_code == 200


def test_deprecated_is_not_disabled(client):
    _aidata, inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}
    _admin(client, "post", "/api/v1/agents/aidata.hermes/deprecate")
    _admin(client, "post", "/api/v1/agents/aidata.hermes/disable")
    hidden = client.get("/api/v1/agents/aidata.hermes", headers=peer)
    assert hidden.status_code == 404
    cannot = _admin(client, "post", "/api/v1/agents/aidata.hermes/deprecate")
    assert cannot.status_code == 409
