from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from sunny_adapter.app import create_adapter_app
from sunny_adapter.config import AdapterSettings
from sunny_adapter.enroll import enroll
from sunny_client import SunnyClient
from sunny_echo.app import create_echo_app
from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


class HostRouter:
    """Route absolute URLs to in-process TestClients by hostname."""

    def __init__(self, clients) -> None:
        self.clients = clients

    def request(self, method, url, **kwargs):
        kwargs.pop("timeout", None)
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path
        if parsed.query:
            path = "{0}?{1}".format(path, parsed.query)
        client = self.clients.get(host)
        if client is None:
            raise RuntimeError("no test client for host {0}".format(host))
        return client.request(method, path, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def close(self):
        for client in self.clients.values():
            client.close()


@pytest.fixture
def trio(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_URL", "http://echo")
    settings = Settings()
    settings.db_path = tmp_path / "echo.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    registry_tc = TestClient(create_app(settings))
    echo_tc = TestClient(create_echo_app())
    registry_http = HostRouter({"registry": registry_tc})

    adapter_settings = AdapterSettings()
    adapter_settings.registry_url = "http://registry"
    adapter_settings.public_url = "http://adapter/sunny/v1"
    adapter_settings.agent_id = "lab.echo"
    adapter_settings.card_path = ROOT / "cards" / "lab.echo.sample.json"
    adapter_settings.mapping_path = ROOT / "sunny_adapter" / "mappings" / "lab.echo.json"
    adapter_settings.admin_token = "admin-test"
    adapter_settings.enroll_token = "enroll-test"
    adapter_settings.key_path = tmp_path / "lab.echo.key"
    adapter_settings.agent_key = ""
    adapter_settings.enrollment_source = "self"

    echo_http = HostRouter({"echo": echo_tc})
    info = enroll(adapter_settings, registry_http)
    adapter_settings.agent_key = info["agent_key"]
    adapter_app = create_adapter_app(
        adapter_settings,
        registry_client=registry_http,
        upstream_client=echo_http,
        auto_enroll=False,
    )
    adapter_tc = TestClient(adapter_app)
    dual = HostRouter({"registry": registry_tc, "adapter": adapter_tc, "echo": echo_tc})

    inspector = dual.post(
        "http://registry/api/v1/agents",
        headers={"X-Sunny-Enroll": "enroll-test"},
        json={
            "card": json.loads((ROOT / "cards" / "lab.inspector.sample.json").read_text(encoding="utf-8")),
            "enrollment_source": "self",
        },
    )
    assert inspector.status_code == 200, inspector.text
    beat = dual.post(
        "http://registry/api/v1/agents/lab.echo/heartbeat",
        headers={"X-Sunny-Agent-Key": info["agent_key"]},
    )
    assert beat.status_code == 200, beat.text

    client = SunnyClient("http://registry", agent_key=inspector.json()["agent_key"], client=dual)
    yield {
        "client": client,
        "dual": dual,
        "echo": echo_tc,
        "adapter": adapter_tc,
        "echo_key": info["agent_key"],
        "inspector_key": inspector.json()["agent_key"],
    }
    dual.close()


def test_echo_http_health_and_ping():
    echo = TestClient(create_echo_app())
    health = echo.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "sunny-echo"
    ping = echo.post("/v1/echo", json={"q": "hello", "trace_id": "t-echo"})
    assert ping.status_code == 200
    body = ping.json()
    assert body["ready"] is True
    assert body["query"] == "hello"
    assert body["trace_id"] == "t-echo"


def test_lab_echo_card_validates():
    from sunny_registry.card_validate import validate_card

    card = json.loads((ROOT / "cards" / "lab.echo.sample.json").read_text(encoding="utf-8"))
    assert validate_card(card) == []
    assert card["capabilities"]["extendedAgentCard"] is True


def test_inspector_search_ticket_invoke_echo(trio):
    client = trio["client"]
    found = client.search(skill="echo.ping")
    assert found["count"] == 1
    assert found["items"][0]["agent_id"] == "lab.echo"

    result = client.invoke("echo.ping", {"query": "pong-me", "trace_id": "echo-loop"})
    assert result["ready"] is True
    assert result["query"] == "pong-me"
    assert result["trace_id"] == "echo-loop"
    assert result["_ticket"]["callee_id"] == "lab.echo"

    hidden = client.search(skill="echo.secret")
    assert hidden["count"] == 0

    denied = trio["dual"].post(
        "http://registry/api/v1/tickets",
        headers={"X-Sunny-Agent-Key": trio["inspector_key"]},
        json={"callee_id": "lab.echo", "skill_id": "echo.secret"},
    )
    assert denied.status_code == 403
    assert "restricted" in denied.json()["detail"]

    public = trio["dual"].get(
        "http://registry/api/v1/agents/lab.echo",
        headers={"X-Sunny-Agent-Key": trio["inspector_key"]},
    )
    assert public.status_code == 200
    public_ids = [skill["id"] for skill in public.json()["card"]["skills"]]
    assert "echo.ping" in public_ids
    assert "echo.secret" not in public_ids
    assert public.json()["card_view"] == "public"

    extended = trio["dual"].get(
        "http://registry/api/v1/agents/lab.echo/extended",
        headers={"X-Sunny-Agent-Key": trio["inspector_key"]},
    )
    assert extended.status_code == 200
    ext_ids = [skill["id"] for skill in extended.json()["card"]["skills"]]
    assert "echo.secret" in ext_ids
    assert extended.json()["card_view"] == "full"
