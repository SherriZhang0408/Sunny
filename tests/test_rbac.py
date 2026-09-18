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


def _owned_card(agent_id: str, name: str) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["name"] = name
    card["description"] = name + " 的说明"
    card["x-sunny"]["agent_id"] = agent_id
    return card


def _new_skill(skill_id: str) -> dict:
    return {
        "id": skill_id,
        "name": "新技能",
        "description": "开发者新增的只读能力。",
        "tags": ["demo", "readonly"],
        "examples": ["试一下"],
        "inputModes": ["application/json"],
        "outputModes": ["application/json"],
        "x-sunny": {
            "data_class": "internal",
            "side_effects": "read",
            "invoke": {"method": "POST", "path": "/sunny/invoke/" + skill_id},
            "when_not_to_use": [],
            "input_schema": {"type": "object", "additionalProperties": True, "properties": {}},
            "output_schema": {"type": "object", "additionalProperties": True, "properties": {}},
        },
    }


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "rbac.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _login(client: TestClient, username: str, password: str):
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    body = res.json()
    return {"Authorization": "Bearer " + body["token"]}, body["user"]


def _publish(client: TestClient, headers: dict, agent_id: str, name: str):
    res = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"card": _owned_card(agent_id, name), "enrollment_source": "hub"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_login_and_me(client):
    denied = client.post("/api/v1/auth/login", json={"username": "developer", "password": "wrong-password"})
    assert denied.status_code == 401
    headers, user = _login(client, "developer", "dev-test-password")
    assert user["role"] == "developer"
    assert user["permissions"]["view_cards"] is True
    assert user["permissions"]["manage_all_agents"] is False
    assert user["permissions"]["publish"] is True
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "developer"


def test_admin_token_still_works(client):
    res = client.get("/api/v1/agents", headers={"Authorization": "Bearer admin-test"})
    assert res.status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer admin-test"})
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_developer_can_view_cards_but_not_admin_surfaces(client):
    client.post(
        "/api/v1/agents",
        headers={"Authorization": "Bearer admin-test"},
        json={"card": _card("aidata.hermes.sample.json"), "enrollment_source": "hub"},
    )
    headers, _ = _login(client, "developer", "dev-test-password")
    listed = client.get("/api/v1/agents", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    detail = client.get("/api/v1/agents/aidata.hermes", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["can_manage"] is False
    assert detail.json()["can_delete"] is False
    assert client.get("/api/v1/activity", headers=headers).status_code == 403
    assert client.get("/api/v1/graph", headers=headers).status_code == 403
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    assert client.get("/api/v1/join", params={"include_token": "1"}, headers=headers).status_code == 403
    assert client.post("/api/v1/agents/aidata.hermes/disable", headers=headers).status_code == 403
    assert client.post("/api/v1/agents/aidata.hermes/keys", headers=headers).status_code == 403


def test_developer_owns_published_agent(client):
    headers, user = _login(client, "developer", "dev-test-password")
    created = _publish(client, headers, "lab.builder", "实验室构建 Agent")
    assert created["created_by"] == user["user_id"]
    assert created["owner_username"] == "developer"
    assert created["can_manage"] is True
    assert created["can_delete"] is True

    patched = client.patch(
        "/api/v1/agents/lab.builder",
        headers=headers,
        json={
            "description": "开发者改过的说明",
            "add_skills": [_new_skill("lab.ping")],
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["description"] == "开发者改过的说明"
    assert {skill["id"] for skill in body["card"]["skills"]} == {"catalog.lookup", "lab.ping"}

    removed = client.patch(
        "/api/v1/agents/lab.builder",
        headers=headers,
        json={"remove_skill_ids": ["lab.ping"]},
    )
    assert removed.status_code == 200
    assert [skill["id"] for skill in removed.json()["card"]["skills"]] == ["catalog.lookup"]

    deleted = client.delete("/api/v1/agents/lab.builder", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/agents/lab.builder", headers=headers).status_code == 404


def test_developer_cannot_modify_others_agent(client):
    admin_headers, _ = _login(client, "admin", "admin-test")
    _publish(client, admin_headers, "lab.adminown", "管理员的智能体")
    extra = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"username": "alice", "password": "alice-secret", "role": "developer"},
    )
    assert extra.status_code == 200, extra.text
    alice, _ = _login(client, "alice", "alice-secret")
    assert client.patch(
        "/api/v1/agents/lab.adminown",
        headers=alice,
        json={"description": "不该改成功"},
    ).status_code == 403
    assert client.delete("/api/v1/agents/lab.adminown", headers=alice).status_code == 403


def test_admin_can_modify_and_delete_any_agent(client):
    dev_headers, _ = _login(client, "developer", "dev-test-password")
    _publish(client, dev_headers, "lab.builder", "实验室构建 Agent")
    admin_headers, _ = _login(client, "admin", "admin-test")
    patched = client.patch(
        "/api/v1/agents/lab.builder",
        headers=admin_headers,
        json={"name": "管理员改名"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "管理员改名"
    assert client.delete("/api/v1/agents/lab.builder", headers=admin_headers).status_code == 200


def test_cannot_delete_last_admin(client):
    headers, user = _login(client, "admin", "admin-test")
    res = client.delete("/api/v1/users/" + user["user_id"], headers=headers)
    assert res.status_code == 409
