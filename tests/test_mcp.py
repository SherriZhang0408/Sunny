from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry.join import WHEN_TO_USE
from sunny_registry.mcp import TOOLS
from sunny_registry.mcp_stdio import decode_buffer, encode_message

MCP_TOOL_NAMES = [item["name"] for item in TOOLS]

ROOT = Path(__file__).resolve().parents[1]


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "mcp.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def _rpc(client: TestClient, method: str, params=None, headers=None, rpc_id=1):
    body = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers or {})


def _call(client: TestClient, name: str, arguments=None, headers=None):
    return _rpc(
        client,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
        headers=headers,
    )


def _structured(res) -> dict:
    assert res.status_code == 200, res.text
    payload = res.json()
    assert "result" in payload, payload
    return payload["result"]["structuredContent"]


def _register_pair(client: TestClient):
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
    _admin(client, "post", "/api/v1/agents/aidata.hermes/heartbeat")
    _admin(client, "post", "/api/v1/agents/lab.inspector/heartbeat")
    return inspector.json()


def test_get_mcp_lists_discovery_tools_only(client):
    res = client.get("/mcp")
    assert res.status_code == 200
    body = res.json()
    names = [item["name"] for item in body["tools"]]
    assert names == MCP_TOOL_NAMES
    assert "list_agents" in names
    assert "describe_access" in names
    assert "list_card_changes" in names
    assert "invoke" not in names
    assert "tickets" not in names
    assert "本机全部 tools" in body["instructions"]


def test_tools_list_has_no_invoke_or_tickets(client):
    listed = _rpc(client, "tools/list")
    assert listed.status_code == 200
    names = [item["name"] for item in listed.json()["result"]["tools"]]
    assert names == MCP_TOOL_NAMES
    assert "invoke" not in names
    assert "tickets" not in names


def test_anonymous_can_join_but_not_search(client):
    joined = _call(client, "join")
    summary = _structured(joined)
    assert summary["role"] == "enterprise_agent_registry"
    enroll = summary["enroll"]
    assert enroll.get("token") is None
    assert enroll["token_included"] is False
    assert "enroll-test" not in json.dumps(summary)
    assert summary["when_to_use"] == WHEN_TO_USE
    assert summary["when_not_to_use"]

    denied = _call(client, "search_registry", {"skill": "catalog.lookup"})
    assert denied.status_code == 200
    assert denied.json()["error"]["code"] == -32401


def test_peer_search_and_card_split(client):
    inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    found = _structured(_call(client, "search_registry", {"skill": "collect.volume.query"}, peer))
    assert found["count"] == 1
    assert found["items"][0]["agent_id"] == "aidata.hermes"
    dumped = json.dumps(found)
    assert "sak_" not in dumped
    assert "ticket" not in dumped
    assert "card_source_url" not in dumped
    assert "supportedInterfaces" not in dumped

    hidden = _structured(_call(client, "search_registry", {"skill": "lab.secret.lookup"}, peer))
    assert hidden["count"] == 0

    card = _structured(_call(client, "get_card", {"agent_id": "lab.inspector"}, peer))
    ids = [skill["id"] for skill in card["card"]["skills"]]
    assert "catalog.lookup" in ids
    assert "lab.secret.lookup" not in ids
    assert card["card_view"] == "public"
    assert card["access"]["discovery_equals_access"] is False
    assert card["access"]["ticket"]["url"].endswith("/api/v1/tickets")

    extended = _structured(_call(client, "get_extended_card", {"agent_id": "lab.inspector"}, peer))
    ext_ids = [skill["id"] for skill in extended["card"]["skills"]]
    assert "lab.secret.lookup" in ext_ids
    assert extended["card_view"] == "full"
    assert "ticket" not in extended
    assert "agent_key" not in extended
    assert "sak_" not in json.dumps(extended)


def test_tools_call_rejects_tickets_and_invoke(client):
    inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}
    for name in ("tickets", "invoke", "issue_ticket"):
        res = _call(client, name, {}, peer)
        assert res.status_code == 200
        assert res.json()["error"]["code"] == -32404
        assert "unknown tool" in res.json()["error"]["message"]


def test_initialize_carries_escalation_instructions(client):
    res = _rpc(client, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    assert res.status_code == 200
    instructions = res.json()["result"]["instructions"]
    assert "不签发调用票" in instructions
    assert "要来：" in instructions
    assert "不要来：" in instructions


def test_list_agents_and_describe_access(client):
    inspector = _register_pair(client)
    peer = {"X-Sunny-Agent-Key": inspector["agent_key"]}

    catalog = _structured(_call(client, "list_agents", {}, peer))
    ids = {item["agent_id"] for item in catalog["items"]}
    assert ids == {"aidata.hermes", "lab.inspector"}
    hermes = next(item for item in catalog["items"] if item["agent_id"] == "aidata.hermes")
    skill_ids = {skill["id"] for skill in hermes["skills"]}
    assert "collect.strategy.query" in skill_ids
    assert "lab.secret.lookup" not in json.dumps(catalog)
    assert hermes["access"]["invoke"]["sidecar_url"]
    assert hermes["access"]["ticket"]["url"].endswith("/api/v1/tickets")
    assert "sak_" not in json.dumps(catalog)

    access = _structured(
        _call(
            client,
            "describe_access",
            {"agent_id": "aidata.hermes", "skill_id": "collect.strategy.query"},
            peer,
        )
    )
    assert access["visible"] is True
    assert access["access"]["peer_may_request_ticket"] is True
    assert access["access"]["invoke"]["path"] == "/sunny/invoke/collect.strategy.query"
    assert access["access"]["invoke"]["url"].endswith("/sunny/invoke/collect.strategy.query")
    assert access["access"]["ticket"]["body"] == {
        "callee_id": "aidata.hermes",
        "skill_id": "collect.strategy.query",
    }

    secret = _structured(
        _call(
            client,
            "describe_access",
            {"agent_id": "lab.inspector", "skill_id": "lab.secret.lookup"},
            peer,
        )
    )
    assert secret["visible"] is False
    assert secret["access"]["peer_may_request_ticket"] is False
    assert secret["access"]["reason"] == "restricted skills are not callable by peers"

    denied = _call(client, "list_agents")
    assert denied.json()["error"]["code"] == -32401


def test_stdio_frames_roundtrip():
    payload = {"jsonrpc": "2.0", "id": 7, "method": "ping"}
    framed = encode_message(payload)
    decoded, rest = decode_buffer(framed)
    assert decoded == payload
    assert rest == b""
    assert decode_buffer(framed[:8]) == (None, framed[:8])


def test_jsonrpc_rejects_invalid_and_unknown(client):
    not_obj = client.post("/mcp", json=["nope"])
    assert not_obj.status_code == 200
    assert not_obj.json()["error"]["code"] == -32600
    bad_ver = _rpc(client, "ping")
    # valid ping
    assert bad_ver.status_code == 200
    unknown = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tickets/issue"})
    assert unknown.json()["error"]["code"] == -32601
    nameless = _rpc(client, "tools/call", {"arguments": {}})
    assert nameless.json()["error"]["code"] == -32602
    note = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202
