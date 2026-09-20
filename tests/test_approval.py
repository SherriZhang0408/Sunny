from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry.policy import APPROVAL_PENDING, APPROVAL_REJECTED, initial_approval_status
from sunny_registry.pull import USER_AGENT

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def _clone(agent_id: str, name: str, **sunny) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["name"] = name
    card["description"] = name + " 的说明"
    card["x-sunny"]["agent_id"] = agent_id
    card["x-sunny"].update(sunny)
    return card


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "approval.db"
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


def _dev(client: TestClient):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "developer", "password": "dev-test-password"},
    )
    assert login.status_code == 200
    return {"Authorization": "Bearer " + login.json()["token"]}


def test_initial_approval_helper():
    assert initial_approval_status("approval_required") == APPROVAL_PENDING
    assert initial_approval_status("registered_peers") == "none"


def test_pending_hidden_until_admin_approves(client):
    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert inspector.status_code == 200
    pending = _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _clone("lab.pending", "待审批巡检", discovery="approval_required"), "enrollment_source": "hub"},
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["discovery"] == "approval_required"
    assert pending.json()["approval_status"] == "pending"

    peer = {"X-Sunny-Agent-Key": inspector.json()["agent_key"]}
    listed = client.get("/api/v1/agents", headers=peer)
    assert "lab.pending" not in {item["agent_id"] for item in listed.json()["items"]}
    assert client.get("/api/v1/agents/lab.pending", headers=peer).status_code == 404
    assert client.get("/api/v1/search", params={"q": "待审批"}, headers=peer).json()["count"] == 0
    denied = client.post(
        "/api/v1/tickets",
        json={"callee_id": "lab.pending", "skill_id": "catalog.lookup"},
        headers=peer,
    )
    assert denied.status_code == 403

    queue = _admin(client, "get", "/api/v1/approvals")
    assert queue.status_code == 200
    assert [item["agent_id"] for item in queue.json()["items"]] == ["lab.pending"]

    approved = _admin(client, "post", "/api/v1/agents/lab.pending/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["discovery"] == "registered_peers"
    assert approved.json()["approval_status"] == "approved"

    _admin(client, "post", "/api/v1/agents/lab.pending/heartbeat")
    visible = client.get("/api/v1/search", params={"q": "待审批"}, headers=peer)
    assert visible.json()["count"] == 1
    assert visible.json()["items"][0]["agent_id"] == "lab.pending"


def test_developer_cannot_self_approve(client):
    headers = _dev(client)
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"card": _clone("dev.pending", "开发者待审", discovery="approval_required"), "enrollment_source": "hub"},
    )
    assert created.status_code == 200
    assert created.json()["approval_status"] == "pending"
    listed = client.get("/api/v1/agents", headers=headers)
    assert "dev.pending" in {item["agent_id"] for item in listed.json()["items"]}

    forbidden = client.post("/api/v1/agents/dev.pending/approve", headers=headers)
    assert forbidden.status_code == 403
    queue = client.get("/api/v1/approvals", headers=headers)
    assert queue.status_code == 403

    card = created.json()["card"]
    card["x-sunny"]["discovery"] = "registered_peers"
    sneak = client.put(
        "/api/v1/agents/dev.pending",
        headers=headers,
        json={"card": card},
    )
    assert sneak.status_code == 403
    assert "self-approve" in sneak.json()["detail"]


def test_reject_keeps_hidden_and_resubmit_requeues(client):
    headers = _dev(client)
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"card": _clone("dev.reject", "将被拒绝", discovery="approval_required"), "enrollment_source": "hub"},
    )
    assert created.status_code == 200
    missing = _admin(client, "post", "/api/v1/agents/dev.reject/reject", json={"reason": ""})
    assert missing.status_code == 400
    rejected = _admin(
        client,
        "post",
        "/api/v1/agents/dev.reject/reject",
        json={"reason": "技能说明不够清楚"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["approval_status"] == APPROVAL_REJECTED
    assert rejected.json()["approval_reason"] == "技能说明不够清楚"
    assert rejected.json()["discovery"] == "approval_required"

    inspector = client.post(
        "/api/v1/agents",
        json={"card": _card("lab.inspector.sample.json"), "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    ).json()
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}
    assert client.get("/api/v1/agents/dev.reject", headers=peer).status_code == 404

    patched = client.patch(
        "/api/v1/agents/dev.reject",
        headers=headers,
        json={"description": "补了一句只读技能说明"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["approval_status"] == "pending"
    assert not patched.json()["approval_reason"]
    queue = _admin(client, "get", "/api/v1/approvals")
    assert "dev.reject" in {item["agent_id"] for item in queue.json()["items"]}


def test_pull_can_mark_approval_required(client):
    card = _clone("lab.pulled", "拉取待审", discovery="registered_peers")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("user-agent") == USER_AGENT
        if request.url.path.endswith("/agent-card.json"):
            return httpx.Response(200, json=card)
        return httpx.Response(404)

    client.app.state.store.settings.http_transport = httpx.MockTransport(handler)
    client.app.state.store.settings.pull_timeout_s = 0.5
    pulled = _admin(
        client,
        "post",
        "/api/v1/agents/pull",
        json={"url": "http://sidecar.test:8091", "discovery": "approval_required"},
    )
    assert pulled.status_code == 200, pulled.text
    assert pulled.json()["agent_id"] == "lab.pulled"
    assert pulled.json()["discovery"] == "approval_required"
    assert pulled.json()["approval_status"] == "pending"
    queue = _admin(client, "get", "/api/v1/approvals")
    assert "lab.pulled" in {item["agent_id"] for item in queue.json()["items"]}


def test_approve_and_reject_are_observed(client):
    _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _clone("lab.obs", "观测审批", discovery="approval_required"), "enrollment_source": "hub"},
    )
    _admin(client, "post", "/api/v1/agents/lab.obs/approve")
    activity = _admin(client, "get", "/api/v1/activity", params={"kind": "card", "q": "approve"})
    assert activity.status_code == 200
    summaries = [item["summary"] for item in activity.json()["items"]]
    assert any("approve lab.obs" in text or text == "card approved" for text in summaries)


def test_approvals_requires_admin(client):
    res = client.get("/api/v1/approvals")
    assert res.status_code in {401, 403}


def test_approvals_rejects_unknown_status(client):
    res = _admin(client, "get", "/api/v1/approvals", params={"status": "maybe"})
    assert res.status_code == 400


def test_approve_non_pending_conflicts(client):
    _admin(
        client,
        "post",
        "/api/v1/agents",
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    res = _admin(client, "post", "/api/v1/agents/aidata.hermes/approve")
    assert res.status_code == 409
