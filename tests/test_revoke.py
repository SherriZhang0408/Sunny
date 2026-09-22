from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from sunny_adapter.app import create_adapter_app
from sunny_adapter.config import AdapterSettings
from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "revoke.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def _register(client: TestClient, card: dict) -> dict:
    res = client.post(
        "/api/v1/agents",
        json={"card": card, "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _issue(client: TestClient, caller_key: str, callee_id: str, skill_id: str) -> dict:
    res = client.post(
        "/api/v1/tickets",
        json={"callee_id": callee_id, "skill_id": skill_id},
        headers={"X-Sunny-Agent-Key": caller_key},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _verify(client: TestClient, callee_key: str, token: str, callee_id: str, skill_id: str):
    return client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": callee_id, "skill_id": skill_id},
        headers={"X-Sunny-Agent-Key": callee_key},
    )


def test_disable_revokes_ticket_after_reenable(client):
    aidata = _register(client, _card("aidata.hermes.sample.json"))
    inspector = _register(client, _card("lab.inspector.sample.json"))
    issued = _issue(client, inspector["agent_key"], "aidata.hermes", "collect.volume.query")
    token = issued["ticket"]
    assert _verify(client, aidata["agent_key"], token, "aidata.hermes", "collect.volume.query").status_code == 200

    disabled = _admin(client, "post", "/api/v1/agents/aidata.hermes/disable")
    assert disabled.status_code == 200
    blocked = _verify(client, aidata["agent_key"], token, "aidata.hermes", "collect.volume.query")
    assert blocked.status_code == 409

    enabled = _admin(client, "post", "/api/v1/agents/aidata.hermes/enable")
    assert enabled.json()["lifecycle"] == "registered"
    revoked = _verify(client, aidata["agent_key"], token, "aidata.hermes", "collect.volume.query")
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "ticket revoked"

    fresh = _issue(client, inspector["agent_key"], "aidata.hermes", "collect.volume.query")
    assert fresh["jti"] != issued["jti"]
    assert _verify(client, aidata["agent_key"], fresh["ticket"], "aidata.hermes", "collect.volume.query").status_code == 200

    activity = _admin(client, "get", "/api/v1/activity", params={"kind": "ticket"}).json()["items"]
    assert any((item.get("detail") or {}).get("reason") == "disabled" for item in activity)


def test_reject_revokes_open_ticket(client):
    inspector = _register(client, _card("lab.inspector.sample.json"))
    gated_card = _card("aidata.hermes.sample.json")
    gated_card["name"] = "待审批数据"
    gated_card["x-sunny"]["agent_id"] = "lab.gated"
    gated_card["x-sunny"]["discovery"] = "approval_required"
    gated = _register(client, gated_card)
    issued = _admin(
        client,
        "post",
        "/api/v1/tickets",
        json={
            "caller_id": "lab.inspector",
            "callee_id": "lab.gated",
            "skill_id": "collect.volume.query",
        },
    )
    assert issued.status_code == 200, issued.text
    token = issued.json()["ticket"]
    assert _verify(client, gated["agent_key"], token, "lab.gated", "collect.volume.query").status_code == 200

    rejected = _admin(client, "post", "/api/v1/agents/lab.gated/reject", json={"reason": "范围过大"})
    assert rejected.status_code == 200, rejected.text
    revoked = _verify(client, gated["agent_key"], token, "lab.gated", "collect.volume.query")
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "ticket revoked"
    assert inspector["agent_id"] == "lab.inspector"


def test_version_revert_does_not_revive_ticket(client):
    aidata = _register(client, _card("aidata.hermes.sample.json"))
    inspector = _register(client, _card("lab.inspector.sample.json"))
    issued = _issue(client, inspector["agent_key"], "aidata.hermes", "collect.volume.query")
    token = issued["ticket"]
    bumped = _admin(client, "patch", "/api/v1/agents/aidata.hermes", json={"version": "0.1.1"})
    assert bumped.status_code == 200
    stale = _verify(client, aidata["agent_key"], token, "aidata.hermes", "collect.volume.query")
    assert stale.status_code == 401
    assert "card version" in stale.json()["detail"]

    reverted = _admin(client, "patch", "/api/v1/agents/aidata.hermes", json={"version": "0.1.0"})
    assert reverted.json()["version"] == "0.1.0"
    revived = _verify(client, aidata["agent_key"], token, "aidata.hermes", "collect.volume.query")
    assert revived.status_code == 401
    assert revived.json()["detail"] == "ticket revoked"


class _LockedRegistry:
    def __init__(self, registry: TestClient) -> None:
        self.registry = registry
        self.lock = threading.Lock()

    def _path(self, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path = "{0}?{1}".format(path, parsed.query)
        return path

    def post(self, url, **kwargs):
        with self.lock:
            return self.registry.post(self._path(url), **kwargs)

    def get(self, url, **kwargs):
        with self.lock:
            return self.registry.get(self._path(url), **kwargs)


def test_inflight_http_stops_when_callee_disabled(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "inflight.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    registry_tc = TestClient(create_app(settings))
    echo = _register(registry_tc, _card("lab.echo.sample.json"))
    inspector = _register(registry_tc, _card("lab.inspector.sample.json"))
    issued = _issue(registry_tc, inspector["agent_key"], "lab.echo", "echo.ping")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self.server.started.set()
            self.server.release.wait(8)
            try:
                body = b'{"ready":true,"query":"hold","trace_id":"late"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                return

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.started = threading.Event()
    server.release = threading.Event()
    port = server.server_address[1]
    daemon = threading.Thread(target=server.serve_forever, daemon=True)
    daemon.start()

    mapping = tmp_path / "lab.echo.json"
    mapping.write_text(
        json.dumps(
            {
                "agent_id": "lab.echo",
                "routes": [
                    {
                        "skill_id": "echo.ping",
                        "handler": "http",
                        "method": "POST",
                        "url": "http://127.0.0.1:{0}/hold".format(port),
                        "timeout_s": 3,
                        "map": {"q": "$.slots.query"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    locked = _LockedRegistry(registry_tc)
    adapter_settings = AdapterSettings()
    adapter_settings.registry_url = "http://registry"
    adapter_settings.public_url = "http://adapter/sunny/v1"
    adapter_settings.agent_id = "lab.echo"
    adapter_settings.card_path = ROOT / "cards" / "lab.echo.sample.json"
    adapter_settings.mapping_path = mapping
    adapter_settings.agent_key = echo["agent_key"]
    adapter_settings.revoke_poll_s = 0.05
    adapter_tc = TestClient(
        create_adapter_app(
            adapter_settings,
            registry_client=locked,
            upstream_client=httpx.Client(),
            auto_enroll=False,
        )
    )

    box = {}

    def call():
        box["res"] = adapter_tc.post(
            "/sunny/invoke/echo.ping",
            headers={"Authorization": "Bearer {0}".format(issued["ticket"])},
            json={"slots": {"query": "hold", "trace_id": "inflight"}},
        )

    worker = threading.Thread(target=call, daemon=True)
    try:
        worker.start()
        assert server.started.wait(3)
        with locked.lock:
            disabled = registry_tc.post(
                "/api/v1/agents/lab.echo/disable",
                headers={"Authorization": "Bearer admin-test"},
            )
        assert disabled.status_code == 200, disabled.text
        worker.join(4)
        assert "res" in box
        assert box["res"].status_code == 409
        assert box["res"].json()["detail"] == "ticket revoked"
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()
        adapter_tc.close()
        registry_tc.close()
