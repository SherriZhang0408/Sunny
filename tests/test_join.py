from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry.join import (
    PLACEHOLDER_URL,
    TOKEN_PLACEHOLDER,
    WHEN_TO_USE,
    build_join_payload,
    mcp_tool_names,
    render_join_markdown,
)

ROOT = Path(__file__).resolve().parents[1]


def _client(tmp_path, public_url="http://192.0.2.10:8088"):
    settings = Settings()
    settings.db_path = tmp_path / "join.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    settings.public_url = public_url
    settings.listen_host = "0.0.0.0"
    settings.listen_port = 8088
    return TestClient(create_app(settings))


def test_join_md_matches_repo_snapshot():
    class Snap(object):
        public_url = PLACEHOLDER_URL
        listen_host = "0.0.0.0"
        listen_port = 8088
        enroll_token = "must-not-appear"

    expected = render_join_markdown(build_join_payload(Snap(), None, False))
    assert (ROOT / "docs" / "join.md").read_text(encoding="utf-8") == expected
    assert "must-not-appear" not in expected


def test_health_advertises_join(tmp_path):
    client = _client(tmp_path)
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["role"] == "enterprise_agent_registry"
    assert body["public_url"] == "http://192.0.2.10:8088"
    assert body["join"] == "/api/v1/join.md"


def test_join_json_and_md_are_public(tmp_path):
    client = _client(tmp_path)
    js = client.get("/api/v1/join")
    assert js.status_code == 200
    body = js.json()
    assert body["role"] == "enterprise_agent_registry"
    assert body["public_url"] == "http://192.0.2.10:8088"
    assert body["listen"]["host"] == "0.0.0.0"
    assert body["enroll"]["header"] == "X-Sunny-Enroll"
    assert body["enroll"]["token"] == TOKEN_PLACEHOLDER
    assert body["enroll"]["token_included"] is False
    assert body["pull"]["path"] == "/api/v1/agents/pull"
    assert body["mcp"]["path"] == "/mcp"
    assert body["mcp"]["tools"] == mcp_tool_names()
    assert body["mcp"]["stdio"] == "python3 -m sunny_registry.mcp_stdio"
    assert "list_agents" in body["mcp"]["tools"]
    assert "describe_access" in body["mcp"]["tools"]
    assert "invoke" not in body["mcp"]["tools"]
    assert body["when_to_use"] == WHEN_TO_USE
    assert body["when_not_to_use"]
    assert "0.0.0.0" not in body["public_url"]

    md = client.get("/api/v1/join.md")
    assert md.status_code == 200
    assert "text/markdown" in md.headers["content-type"]
    text = md.text
    assert "企业注册中心" in text
    assert "只交基址" in text
    assert "何时来 Registry" in text
    assert "本机能力优先" in text
    assert "也可经 MCP 发现目录" in text
    assert "card-changes" in text
    assert "list_card_changes" in body["mcp"]["tools"]
    assert "http://192.0.2.10:8088/mcp" in text
    assert "http://192.0.2.10:8088/api/v1/agents/pull" in text
    assert "http://192.0.2.10:8088/api/v1/agents" in text
    assert TOKEN_PLACEHOLDER in text
    assert "enroll-test" not in text
    assert "0.0.0.0" not in body["card_skeleton"]["supportedInterfaces"][0]["url"]


def test_join_token_requires_admin(tmp_path):
    client = _client(tmp_path)
    denied = client.get("/api/v1/join.md", params={"include_token": "1"})
    assert denied.status_code == 403
    allowed = client.get(
        "/api/v1/join.md",
        params={"include_token": "1", "download": "1"},
        headers={"Authorization": "Bearer admin-test"},
    )
    assert allowed.status_code == 200
    assert "enroll-test" in allowed.text
    assert 'attachment; filename="sunny-join.md"' in allowed.headers.get("content-disposition", "")
