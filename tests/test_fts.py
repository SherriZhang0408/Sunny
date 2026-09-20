from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry import fts

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "fts.db"
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
    assert _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat").status_code == 200
    assert _admin(client, "post", "/api/v1/agents/lab.inspector/heartbeat").status_code == 200
    return hermes.json(), inspector.json()


def test_health_advertises_fts(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["fts"]["ready"] is True


def test_search_hits_card_description(client):
    _seed_pair(client)
    headers = {"Authorization": "Bearer admin-test"}
    res = client.get("/api/v1/search", params={"q": "自己不调模型"}, headers=headers)
    assert res.status_code == 200
    assert [item["agent_id"] for item in res.json()["items"]] == ["lab.inspector"]


def test_search_hits_skill_description(client):
    _seed_pair(client)
    headers = {"Authorization": "Bearer admin-test"}
    res = client.get("/api/v1/search", params={"q": "不返回预览图"}, headers=headers)
    assert res.status_code == 200
    assert [item["agent_id"] for item in res.json()["items"]] == ["aidata.hermes"]


def test_search_hits_example_phrase(client):
    _seed_pair(client)
    headers = {"Authorization": "Bearer admin-test"}
    res = client.get("/api/v1/search", params={"q": "谁会查"}, headers=headers)
    assert res.status_code == 200
    assert [item["agent_id"] for item in res.json()["items"]] == ["lab.inspector"]


def test_search_does_not_leak_restricted_skill_text(client):
    _seed_pair(client)
    headers = {"Authorization": "Bearer admin-test"}
    res = client.get("/api/v1/search", params={"q": "lab.secret.lookup"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["items"] == []


def test_list_agents_q_uses_description(client):
    _seed_pair(client)
    res = _admin(client, "get", "/api/v1/agents", params={"q": "不开放模型调用"})
    assert res.status_code == 200
    assert [item["agent_id"] for item in res.json()["items"]] == ["aidata.hermes"]


def test_fts_operators_do_not_500(client):
    _seed_pair(client)
    headers = {"Authorization": "Bearer admin-test"}
    res = client.get("/api/v1/search", params={"q": 'volume" OR *'}, headers=headers)
    assert res.status_code == 200
    assert [item["agent_id"] for item in res.json()["items"]] == ["aidata.hermes"]


def test_update_card_reindexes_description(client):
    _seed_pair(client)
    card = _card("lab.inspector.sample.json")
    card["description"] = "这张卡专门负责圈宠场景对照。"
    updated = _admin(client, "put", "/api/v1/agents/lab.inspector", json={"card": card})
    assert updated.status_code == 200, updated.text
    headers = {"Authorization": "Bearer admin-test"}
    hit = client.get("/api/v1/search", params={"q": "圈宠场景对照"}, headers=headers)
    assert [item["agent_id"] for item in hit.json()["items"]] == ["lab.inspector"]
    miss = client.get("/api/v1/search", params={"q": "自己不调模型"}, headers=headers)
    assert miss.json()["items"] == []


def test_delete_agent_drops_fts_row(client):
    _seed_pair(client)
    assert _admin(client, "delete", "/api/v1/agents/lab.inspector").status_code == 200
    headers = {"Authorization": "Bearer admin-test"}
    res = client.get("/api/v1/search", params={"q": "目录探查", "alive": "0"}, headers=headers)
    assert res.json()["items"] == []


def test_match_expr_quotes_tokens():
    assert fts.match_expr("  volume 目录探查 ") == '"volume" OR ("目录" AND "录探" AND "探查")'
    assert fts.match_expr('foo" OR *') == '"foo" OR "OR"'
    assert fts.match_expr('***') is None
