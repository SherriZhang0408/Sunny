from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.a2a_export import card_etag, etag_matches, strip_sunny_extensions
from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def _clone(agent_id: str, **sunny) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["name"] = agent_id
    card["x-sunny"]["agent_id"] = agent_id
    card["x-sunny"].update(sunny)
    return card


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "a2a.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def test_strip_sunny_extensions_drops_enterprise_fields():
    card = _card("aidata.hermes.sample.json")
    exported = strip_sunny_extensions(card)
    dumped = json.dumps(exported)
    assert "x-sunny" not in dumped
    assert "sunny.local" not in dumped
    assert exported["version"] == card["version"]
    assert exported["skills"][0]["id"] == "collect.strategy.query"
    assert "extensions" not in (exported.get("capabilities") or {})
    assert "x-sunny" in json.dumps(card)


def test_card_etag_quotes_version():
    assert card_etag({"version": "0.1.0"}) == '"0.1.0"'
    assert card_etag({}) == '"empty"'
    assert etag_matches('"0.1.0"', '"0.1.0"')
    assert etag_matches('W/"0.1.0"', '"0.1.0"')
    assert etag_matches('"other"', '"0.1.0"') is False


def test_a2a_export_strips_and_caches(client):
    card = _card("aidata.hermes.sample.json")
    created = _admin(client, "post", "/api/v1/agents", json={"card": card, "enrollment_source": "hub"})
    assert created.status_code == 200, created.text

    res = _admin(client, "get", "/api/v1/agents/aidata.hermes/a2a")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "x-sunny" not in json.dumps(body)
    assert body["name"] == card["name"]
    assert body["skills"][0]["id"] == "collect.strategy.query"
    assert res.headers.get("etag") == '"0.1.0"'
    assert "private" in (res.headers.get("cache-control") or "")
    assert res.headers.get("vary") == "Authorization"

    cached = _admin(
        client,
        "get",
        "/api/v1/agents/aidata.hermes/a2a",
        headers={"If-None-Match": '"0.1.0"'},
    )
    assert cached.status_code == 304
    assert cached.headers.get("etag") == '"0.1.0"'


def test_a2a_export_follows_discovery_visibility(client):
    public = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    assert public.status_code == 200, public.text
    private = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _clone("lab.private", discovery="private"), "enrollment_source": "hub"},
    )
    assert private.status_code == 200, private.text
    peer = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert peer.status_code == 200, peer.text
    headers = {"X-Sunny-Agent-Key": peer.json()["agent_key"]}

    visible = client.get("/api/v1/agents/aidata.hermes/a2a", headers=headers)
    assert visible.status_code == 200
    assert "x-sunny" not in json.dumps(visible.json())

    hidden = client.get("/api/v1/agents/lab.private/a2a", headers=headers)
    assert hidden.status_code == 404
    assert _admin(client, "get", "/api/v1/agents/lab.private/a2a").status_code == 200
