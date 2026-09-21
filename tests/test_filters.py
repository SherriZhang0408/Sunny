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
    settings.db_path = tmp_path / "filters.db"
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


def _seed_pair(client: TestClient):
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
    beat = _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat")
    assert beat.status_code == 200
    return hermes.json(), inspector.json()


def test_list_filters_q_workspace_and_source(client):
    _seed_pair(client)

    by_q = _admin(client, "get", "/api/v1/agents", params={"q": "hermes"})
    assert by_q.status_code == 200
    assert [item["agent_id"] for item in by_q.json()["items"]] == ["aidata.hermes"]

    by_ws = _admin(client, "get", "/api/v1/agents", params={"workspace": "ecovacs.lab"})
    assert [item["agent_id"] for item in by_ws.json()["items"]] == ["lab.inspector"]

    hub_only = _admin(client, "get", "/api/v1/agents", params={"enrollment_source": "hub"})
    assert [item["agent_id"] for item in hub_only.json()["items"]] == ["aidata.hermes"]
    self_only = _admin(client, "get", "/api/v1/agents", params={"enrollment_source": "self"})
    assert [item["agent_id"] for item in self_only.json()["items"]] == ["lab.inspector"]


def test_list_runtime_status_online_unknown_disabled(client):
    _seed_pair(client)

    online = _admin(client, "get", "/api/v1/agents", params={"runtime_status": "online"})
    assert [item["agent_id"] for item in online.json()["items"]] == ["aidata.hermes"]
    assert online.json()["items"][0]["runtime_status"] == "online"

    waiting = _admin(client, "get", "/api/v1/agents", params={"runtime_status": "unknown"})
    assert [item["agent_id"] for item in waiting.json()["items"]] == ["lab.inspector"]

    _admin(client, "post", "/api/v1/agents/lab.inspector/disable")
    disabled = _admin(client, "get", "/api/v1/agents", params={"runtime_status": "disabled"})
    assert [item["agent_id"] for item in disabled.json()["items"]] == ["lab.inspector"]


def _clone(agent_id: str, name: str, **sunny) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["name"] = name
    card["description"] = name + " 的说明"
    card["x-sunny"]["agent_id"] = agent_id
    card["x-sunny"].update(sunny)
    return card


def test_list_filters_approval_status(client):
    pending = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _clone("lab.pending", "待审批卡", discovery="approval_required"), "enrollment_source": "hub"},
    )
    assert pending.status_code == 200, pending.text
    approved = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _clone("lab.approved", "已通过卡", discovery="approval_required"), "enrollment_source": "hub"},
    )
    assert approved.status_code == 200, approved.text
    assert _admin(client, "post", "/api/v1/agents/lab.approved/approve").status_code == 200
    _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )

    waiting = _admin(client, "get", "/api/v1/agents", params={"approval_status": "pending"})
    assert [item["agent_id"] for item in waiting.json()["items"]] == ["lab.pending"]
    passed = _admin(client, "get", "/api/v1/agents", params={"approval_status": "approved"})
    assert [item["agent_id"] for item in passed.json()["items"]] == ["lab.approved"]
    rejected = _admin(client, "get", "/api/v1/agents", params={"approval_status": "rejected"})
    assert rejected.json()["items"] == []


def test_search_filters_workspace_and_q(client):
    _seed_pair(client)
    assert _admin(client, "post", "/api/v1/agents/lab.inspector/heartbeat").status_code == 200
    headers = {"Authorization": "Bearer admin-test"}

    by_ws = client.get("/api/v1/search", params={"workspace": "ecovacs.aidata"}, headers=headers)
    assert by_ws.status_code == 200
    assert [item["agent_id"] for item in by_ws.json()["items"]] == ["aidata.hermes"]

    by_q = client.get("/api/v1/search", params={"q": "volume"}, headers=headers)
    assert [item["agent_id"] for item in by_q.json()["items"]] == ["aidata.hermes"]

    by_skill_name = client.get("/api/v1/search", params={"q": "目录探查"}, headers=headers)
    assert [item["agent_id"] for item in by_skill_name.json()["items"]] == ["lab.inspector"]

    empty = client.get("/api/v1/search", params={"workspace": "no.such.space"}, headers=headers)
    assert empty.json()["count"] == 0

    by_tag = client.get("/api/v1/search", params={"tag": "volume"}, headers=headers)
    assert [item["agent_id"] for item in by_tag.json()["items"]] == ["aidata.hermes"]

    no_tag = client.get("/api/v1/search", params={"tag": "no-such-tag"}, headers=headers)
    assert no_tag.json()["count"] == 0
