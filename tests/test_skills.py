from __future__ import annotations

from pathlib import Path

import pytest

from sunny_adapter.config import AdapterSettings
from sunny_adapter.invoke import invoke_skill
from sunny_adapter.skills import dispatch, query_strategy, query_volume
from sunny_echo.app import create_echo_app
from fastapi.testclient import TestClient


def _settings(tmp_path) -> AdapterSettings:
    settings = AdapterSettings()
    settings.aidata_root = tmp_path / "no-aidata"
    settings.card_path = Path(__file__).resolve().parents[1] / "cards" / "aidata.hermes.sample.json"
    settings.mapping_path = (
        Path(__file__).resolve().parents[1] / "sunny_adapter" / "mappings" / "aidata.hermes.json"
    )
    return settings


def test_strategy_query_and_product_filter():
    living = query_strategy({"mission_name": "living_room"})
    assert living["ready"] is True
    assert living["items"]
    assert all(item["mission_name"] == "living_room" for item in living["items"])

    none = query_strategy({"mission_name": "living_room", "product_line": "no-such-line"})
    assert none["items"] == []

    text = query_strategy({"query": "living"})
    assert text["items"]


def test_strategy_requires_query_or_mission():
    with pytest.raises(ValueError):
        query_strategy({})


def test_volume_without_wrapper_is_ready_false(tmp_path):
    settings = _settings(tmp_path)
    out = query_volume({"mission_name": "living_room"}, settings)
    assert out["ready"] is False
    assert out["mock"] is True
    assert out["count"] == 0
    with pytest.raises(ValueError):
        query_volume({}, settings)


def test_dispatch_unknown_skill(tmp_path):
    with pytest.raises(KeyError):
        dispatch("no.such.skill", {}, _settings(tmp_path))


def test_invoke_skill_validates_known_local_route(tmp_path):
    settings = _settings(tmp_path)
    out = invoke_skill("collect.strategy.query", {"mission_name": "living_room"}, settings)
    assert out["ready"] is True
    with pytest.raises(KeyError):
        invoke_skill("echo.secret", {"query": "x"}, settings)


def test_echo_http_prefers_query_over_q():
    client = TestClient(create_echo_app())
    assert client.get("/health").json()["service"] == "sunny-echo"
    res = client.post("/v1/echo", json={"q": "from-q", "query": "from-query", "trace_id": "t"})
    assert res.status_code == 200
    assert res.json() == {"ready": True, "query": "from-query", "trace_id": "t"}
    empty = client.post("/v1/echo", json={})
    assert empty.json()["query"] == ""
