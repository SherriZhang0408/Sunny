from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sunny_adapter.app import create_adapter_app
from sunny_adapter.config import AdapterSettings
from sunny_adapter.mapping import MappingError, apply_map, expand_env, load_mapping
from sunny_adapter.slots import SlotError, validate_slots

ROOT = Path(__file__).resolve().parents[1]


def _hermes_card() -> dict:
    return json.loads((ROOT / "cards" / "aidata.hermes.sample.json").read_text(encoding="utf-8"))


def _echo_card() -> dict:
    return {
        "name": "Echo",
        "description": "测试用 HTTP 映射租户。",
        "version": "0.1.0",
        "supportedInterfaces": [{"url": "http://adapter/sunny/v1", "protocolBinding": "HTTP+JSON"}],
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "echo.ping",
                "name": "回声",
                "description": "把 query 转给下游。",
                "tags": ["test"],
                "x-sunny": {
                    "data_class": "internal",
                    "side_effects": "read",
                    "input_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["query"],
                        "properties": {
                            "query": {"type": "string", "minLength": 1},
                            "trace_id": {"type": "string"},
                        },
                    },
                    "output_schema": {"type": "object"},
                },
            }
        ],
        "x-sunny": {
            "agent_id": "lab.echo",
            "workspace": "ecovacs.lab",
            "discovery": "registered_peers",
            "access_tier": "S1",
            "not_exposed": [],
            "invoke_identity": "agent_service",
            "scratch_access": "none",
        },
    }


class _VerifyClient:
    def post(self, url, **kwargs):
        class _Res:
            status_code = 200
            text = "{}"

            def json(self):
                return {"ok": True, "payload": {"caller": "lab.inspector", "callee": "lab.echo", "skill": "echo.ping"}}

        return _Res()


def test_expand_env_and_defaults(monkeypatch):
    monkeypatch.setenv("ECHO_HOST", "echo.internal")
    assert expand_env("http://${ECHO_HOST}/v1") == "http://echo.internal/v1"
    assert expand_env("http://${MISSING:-fallback}/v1") == "http://fallback/v1"
    with pytest.raises(MappingError, match="unresolved env"):
        expand_env("http://${MISSING}/v1")


def test_apply_map_json_paths():
    body = apply_map({"query": "hello", "trace_id": "t1"}, "echo.ping", {"q": "$.slots.query"})
    assert body == {"q": "hello"}
    envelope = apply_map({"query": "hello", "trace_id": "t1"}, "echo.ping", None)
    assert envelope["skill_id"] == "echo.ping"
    assert envelope["slots"]["query"] == "hello"


def test_validate_slots_accepts_catalog_and_rejects_extra():
    card = _hermes_card()
    validate_slots(card, "collect.strategy.query", {"mission_name": "living_room", "trace_id": "t1"})
    with pytest.raises(SlotError, match="sql"):
        validate_slots(card, "collect.strategy.query", {"mission_name": "living_room", "sql": "select 1"})
    with pytest.raises(SlotError):
        validate_slots(card, "collect.strategy.query", {})


def test_default_hermes_mapping_lists_local_skills():
    path = ROOT / "sunny_adapter" / "mappings" / "aidata.hermes.json"
    mapping = load_mapping(path, "aidata.hermes")
    assert [route["skill_id"] for route in mapping["routes"]] == [
        "collect.strategy.query",
        "collect.volume.query",
    ]
    assert all(route["handler"] == "local" for route in mapping["routes"])


def test_http_route_maps_slots_and_probes_health(tmp_path):
    card_path = tmp_path / "echo.json"
    mapping_path = tmp_path / "echo.mapping.json"
    card_path.write_text(json.dumps(_echo_card(), ensure_ascii=False), encoding="utf-8")
    mapping_path.write_text(
        json.dumps(
            {
                "agent_id": "lab.echo",
                "routes": [
                    {
                        "skill_id": "echo.ping",
                        "handler": "http",
                        "method": "POST",
                        "url": "http://echo.internal/v1/echo",
                        "map": {"q": "$.slots.query"},
                    }
                ],
                "heartbeat": {"url": "http://echo.internal/healthz"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/echo":
            seen["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"pong": seen["body"]["q"]})
        return httpx.Response(404)

    settings = AdapterSettings()
    settings.agent_id = "lab.echo"
    settings.card_path = card_path
    settings.mapping_path = mapping_path
    settings.agent_key = "sak_test"
    settings.public_url = "http://adapter/sunny/v1"
    app = create_adapter_app(
        settings,
        registry_client=_VerifyClient(),
        upstream_client=httpx.Client(transport=httpx.MockTransport(handler)),
        auto_enroll=False,
    )
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["downstream"]["ok"] is True

    invoked = client.post(
        "/sunny/invoke/echo.ping",
        headers={"Authorization": "Bearer ticket"},
        json={"slots": {"query": "hello", "trace_id": "echo-1"}},
    )
    assert invoked.status_code == 200, invoked.text
    body = invoked.json()
    assert body["ready"] is True
    assert body["data"]["pong"] == "hello"
    assert seen["body"] == {"q": "hello"}


def test_mapping_rejects_agent_mismatch_and_http_without_url(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "agent_id": "other.agent",
                "routes": [{"skill_id": "echo.ping", "handler": "local"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(MappingError) as exc:
        load_mapping(path, "lab.echo")
    assert "does not match" in str(exc.value)

    path.write_text(
        json.dumps({"routes": [{"skill_id": "echo.ping", "handler": "http"}]}),
        encoding="utf-8",
    )
    with pytest.raises(MappingError):
        load_mapping(path, "lab.echo")


def test_mapping_missing_env_is_503(tmp_path):
    card_path = tmp_path / "echo.json"
    mapping_path = tmp_path / "echo.mapping.json"
    card_path.write_text(json.dumps(_echo_card(), ensure_ascii=False), encoding="utf-8")
    mapping_path.write_text(
        json.dumps(
            {
                "agent_id": "lab.echo",
                "routes": [
                    {
                        "skill_id": "echo.ping",
                        "handler": "http",
                        "url": "http://${MISSING_UPSTREAM}/v1/echo",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settings = AdapterSettings()
    settings.agent_id = "lab.echo"
    settings.card_path = card_path
    settings.mapping_path = mapping_path
    settings.agent_key = "sak_test"
    app = create_adapter_app(
        settings,
        registry_client=_VerifyClient(),
        upstream_client=httpx.Client(),
        auto_enroll=False,
    )
    res = TestClient(app).post(
        "/sunny/invoke/echo.ping",
        headers={"Authorization": "Bearer ticket"},
        json={"slots": {"query": "hello"}},
    )
    assert res.status_code == 503
    assert "unresolved env" in res.json()["detail"]
