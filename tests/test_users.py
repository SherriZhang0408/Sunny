from __future__ import annotations

from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings


def _client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "users.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def test_admin_lists_and_creates_users(tmp_path):
    client = _client(tmp_path)
    headers = {"Authorization": "Bearer admin-test"}
    listed = client.get("/api/v1/users", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] == 2

    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "bob", "password": "bob-secret", "role": "developer"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["username"] == "bob"
    assert "password" not in created.json()
    assert "password_hash" not in created.json()

    again = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "bob", "password": "bob-secret", "role": "developer"},
    )
    assert again.status_code == 409


def test_create_user_validates_fields(tmp_path):
    client = _client(tmp_path)
    headers = {"Authorization": "Bearer admin-test"}
    assert (
        client.post(
            "/api/v1/users",
            headers=headers,
            json={"username": "1bad", "password": "long-enough", "role": "developer"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/users",
            headers=headers,
            json={"username": "okname", "password": "short", "role": "developer"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/users",
            headers=headers,
            json={"username": "okname", "password": "long-enough", "role": "root"},
        ).status_code
        == 400
    )


def test_developer_cannot_manage_users(tmp_path):
    client = _client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "developer", "password": "dev-test-password"})
    headers = {"Authorization": "Bearer " + login.json()["token"]}
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/users",
            headers=headers,
            json={"username": "eve", "password": "eve-secret", "role": "developer"},
        ).status_code
        == 403
    )


def test_admin_can_delete_other_user_not_missing(tmp_path):
    client = _client(tmp_path)
    headers = {"Authorization": "Bearer admin-test"}
    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "tempdev", "password": "temp-secret", "role": "developer"},
    ).json()
    deleted = client.delete("/api/v1/users/" + created["user_id"], headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    missing = client.delete("/api/v1/users/usr_no_such", headers=headers)
    assert missing.status_code == 404
