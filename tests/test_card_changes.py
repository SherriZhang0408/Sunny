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
    settings.db_path = tmp_path / "card-changes.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def _rpc(client: TestClient, method: str, params=None, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers or {})


def test_version_bump_appears_in_change_feed(client):
    created = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    assert created.status_code == 200
    empty = _admin(client, "get", "/api/v1/card-changes")
    assert empty.json()["items"] == []

    card = _card("aidata.hermes.sample.json")
    card["version"] = "0.1.1"
    updated = _admin(client, "put", "/api/v1/agents/aidata.hermes", json={"card": card})
    assert updated.status_code == 200, updated.text

    feed = _admin(client, "get", "/api/v1/card-changes")
    assert feed.status_code == 200
    items = feed.json()["items"]
    assert len(items) == 1
    assert items[0]["agent_id"] == "aidata.hermes"
    assert items[0]["old_version"] == "0.1.0"
    assert items[0]["new_version"] == "0.1.1"
    next_since = feed.json()["next_since"]
    again = _admin(client, "get", "/api/v1/card-changes", params={"since": next_since})
    assert again.json()["items"] == []


def test_peer_and_mcp_can_read_visible_changes(client):
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
    card = _card("aidata.hermes.sample.json")
    card["version"] = "0.2.0"
    assert _admin(client, "put", "/api/v1/agents/aidata.hermes", json={"card": card}).status_code == 200

    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}
    feed = client.get("/api/v1/card-changes", headers=peer)
    assert feed.status_code == 200
    assert [item["new_version"] for item in feed.json()["items"]] == ["0.2.0"]

    listed = _rpc(
        client,
        "tools/call",
        {"name": "list_card_changes", "arguments": {"agent_id": "aidata.hermes"}},
        headers=peer,
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()["result"]["structuredContent"]
    assert payload["count"] == 1
    assert payload["items"][0]["old_version"] == "0.1.0"
