from __future__ import annotations

from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings


def test_seed_if_empty_registers_demo_pair_and_edge(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "seed.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = True
    client = TestClient(create_app(settings))

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["agents"] == 2

    listed = client.get("/api/v1/agents", headers={"Authorization": "Bearer admin-test"}).json()
    ids = sorted(item["agent_id"] for item in listed["items"])
    assert ids == ["aidata.hermes", "lab.inspector"]

    graph = client.get("/api/v1/graph", headers={"Authorization": "Bearer admin-test"}).json()
    edges = graph["edges"]
    assert any(
        edge["caller_id"] == "lab.inspector"
        and edge["callee_id"] == "aidata.hermes"
        and edge["skill_id"] == "collect.volume.query"
        for edge in edges
    )


def test_seed_skips_demo_pair_when_sample_cards_missing(tmp_path, monkeypatch):
    from sunny_registry import seed as seedmod
    from sunny_registry.config import Settings
    from sunny_registry.db import connect
    from sunny_registry.store import Store

    settings = Settings()
    settings.db_path = tmp_path / "no-cards.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.seed_on_empty = True
    store = Store(connect(settings.db_path), settings)
    monkeypatch.setattr(seedmod, "ROOT", tmp_path)
    seedmod.seed_if_empty(store)
    assert store.count_users() == 2
    assert store.count_agents() == 0


def test_seed_users_only_when_empty(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "users-only.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.seed_on_empty = False
    client = TestClient(create_app(settings))
    users = client.get("/api/v1/users", headers={"Authorization": "Bearer admin-test"}).json()
    names = sorted(item["username"] for item in users["items"])
    assert names == ["admin", "developer"]
    assert client.get("/api/v1/health").json()["agents"] == 0
