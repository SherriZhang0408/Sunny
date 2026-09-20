from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from sunny_adapter.app import create_adapter_app
from sunny_adapter.config import AdapterSettings
from sunny_adapter.enroll import enroll
from sunny_adapter.skills import query_strategy
from sunny_client import SunnyClient, invoke_url
from sunny_client import hermes
from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]


class RoutedClient:
    """Starlette TestClient wrapper that accepts absolute URLs."""

    def __init__(self, registry: TestClient, adapter: TestClient = None) -> None:
        self.registry = registry
        self.adapter = adapter

    def _go(self, method: str, url: str, **kwargs):
        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path = "{0}?{1}".format(path, parsed.query)
        if self.adapter is not None and (
            path.startswith("/sunny/") or path.startswith("/.well-known/")
        ):
            return getattr(self.adapter, method)(path, **kwargs)
        return getattr(self.registry, method)(path, **kwargs)

    def get(self, url, **kwargs):
        return self._go("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._go("post", url, **kwargs)

    def put(self, url, **kwargs):
        return self._go("put", url, **kwargs)

    def close(self):
        self.registry.close()
        if self.adapter is not None:
            self.adapter.close()


@pytest.fixture
def pair(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "reg.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = True
    registry_tc = TestClient(create_app(settings))
    registry_http = RoutedClient(registry_tc)

    adapter_settings = AdapterSettings()
    adapter_settings.registry_url = "http://registry"
    adapter_settings.public_url = "http://adapter/sunny/v1"
    adapter_settings.card_path = ROOT / "cards" / "aidata.hermes.sample.json"
    adapter_settings.admin_token = "admin-test"
    adapter_settings.enroll_token = "enroll-test"
    adapter_settings.key_path = tmp_path / "aidata.key"
    adapter_settings.agent_key = ""
    adapter_settings.aidata_root = tmp_path / "no-aidata"

    info = enroll(adapter_settings, registry_http)
    adapter_settings.agent_key = info["agent_key"]
    adapter_app = create_adapter_app(adapter_settings, registry_client=registry_http, auto_enroll=False)
    adapter_tc = TestClient(adapter_app)
    dual = RoutedClient(registry_tc, adapter_tc)

    minted = dual.post(
        "http://registry/api/v1/agents/lab.inspector/keys",
        headers={"Authorization": "Bearer admin-test"},
    )
    assert minted.status_code == 200, minted.text
    client = SunnyClient("http://registry", agent_key=minted.json()["agent_key"], client=dual)
    yield {
        "adapter": adapter_app,
        "adapter_tc": adapter_tc,
        "client": client,
        "dual": dual,
        "aidata_key": info["agent_key"],
        "enroll": info,
    }
    dual.close()


def test_strategy_catalog_living_room():
    out = query_strategy({"mission_name": "living_room", "trace_id": "t1"})
    assert out["ready"] is True
    assert out["items"][0]["mission_name"] == "living_room"


def test_search_then_invoke_strategy(pair):
    client = pair["client"]
    found = client.search(skill="collect.strategy.query")
    assert found["count"] >= 1
    assert found["items"][0]["agent_id"] == "aidata.hermes"
    result = client.invoke("collect.strategy.query", {"mission_name": "laser", "trace_id": "m2-1"})
    assert result["ready"] is True
    assert result["items"][0]["mission_name"] == "laser"
    assert result["_ticket"]["callee_id"] == "aidata.hermes"


def test_well_known_serves_full_sunny_card(pair):
    from sunny_registry.card_validate import validate_card

    card_res = pair["adapter_tc"].get("/.well-known/agent-card.json")
    alias = pair["adapter_tc"].get("/.well-known/agent.json")
    v1 = pair["adapter_tc"].get("/sunny/v1/card")
    assert card_res.status_code == 200
    assert alias.status_code == 200
    assert v1.status_code == 200
    card = card_res.json()
    assert card == alias.json() == v1.json()
    assert card["x-sunny"]["agent_id"] == "aidata.hermes"
    assert card["supportedInterfaces"][0]["url"] == "http://adapter/sunny/v1"
    assert validate_card(card) == []
    assert card_res.headers.get("etag") == '"0.1.0"'
    assert "max-age=60" in (card_res.headers.get("cache-control") or "")

    cached = pair["adapter_tc"].get(
        "/.well-known/agent-card.json",
        headers={"If-None-Match": '"0.1.0"'},
    )
    assert cached.status_code == 304
    assert cached.headers.get("etag") == '"0.1.0"'


def test_registry_can_pull_adapter_well_known(pair):
    served = json.loads(json.dumps(pair["adapter_tc"].get("/.well-known/agent-card.json").json()))
    served["x-sunny"]["agent_id"] = "lab.fromwell"
    served["name"] = "lab.fromwell"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(200, json=served)
        return httpx.Response(404)

    pair["dual"].registry.app.state.store.settings.http_transport = httpx.MockTransport(handler)
    pair["dual"].registry.app.state.store.settings.pull_timeout_s = 0.5
    res = pair["dual"].post(
        "http://registry/api/v1/agents/pull",
        headers={"Authorization": "Bearer admin-test"},
        json={"url": "http://sidecar.test:8091"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["agent_id"] == "lab.fromwell"
    assert res.json()["card_source_url"].endswith("/.well-known/agent-card.json")


def test_invoke_rejects_missing_ticket(pair):
    res = pair["adapter_tc"].post("/sunny/invoke/collect.strategy.query", json={"slots": {"mission_name": "pet"}})
    assert res.status_code == 401


def test_invoke_rejects_unknown_slot(pair):
    ticket = pair["client"].issue_ticket("aidata.hermes", "collect.strategy.query")
    res = pair["adapter_tc"].post(
        "/sunny/invoke/collect.strategy.query",
        headers={"Authorization": "Bearer {0}".format(ticket["ticket"])},
        json={"slots": {"mission_name": "living_room", "sql": "select 1"}},
    )
    assert res.status_code == 400
    assert "sql" in res.json()["detail"]


def test_health_reports_local_mapping(pair):
    res = pair["adapter_tc"].get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["mapping"]["ok"] is True
    assert "collect.strategy.query" in body["mapping"]["routes"]
    assert body["downstream"]["configured"] is False


def test_volume_without_proxy_is_ready_false(pair):
    result = pair["client"].invoke(
        "collect.volume.query",
        {"mission_name": "living_room", "quest_name": "MetaData", "trace_id": "m2-vol"},
    )
    assert result["ready"] is False
    assert result["mock"] is True
    assert result["es_index"] == "ai_collect"
    assert "dsl" not in result


def test_admin_invoke_needs_caller(pair):
    admin = SunnyClient("http://registry", admin_token="admin-test", client=pair["dual"])
    result = admin.invoke(
        "collect.strategy.query",
        {"mission_name": "pet", "trace_id": "m2-admin"},
        caller_id="lab.inspector",
    )
    assert result["ready"] is True
    assert result["items"][0]["mission_name"] == "pet"


def test_invoke_url_joins_card_path():
    card = json.loads((ROOT / "cards" / "aidata.hermes.sample.json").read_text(encoding="utf-8"))
    card["supportedInterfaces"][0]["url"] = "http://127.0.0.1:8091/sunny/v1"
    assert invoke_url(card, "collect.volume.query") == "http://127.0.0.1:8091/sunny/invoke/collect.volume.query"


def test_enroll_attach_keeps_hub_source(pair):
    assert pair["enroll"]["mode"] == "attach"
    detail = pair["dual"].get(
        "http://registry/api/v1/agents/aidata.hermes",
        headers={"Authorization": "Bearer admin-test"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["enrollment_source"] == "hub"
    assert body["lifecycle"] == "registered"


def test_hermes_discover_and_peer_invoke(pair, monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    found = hermes.discover(skill="collect.strategy.query", client=pair["client"])
    assert found["ready"] is True
    assert found["items"][0]["agent_id"] == "aidata.hermes"
    assert "card" not in found["items"][0]

    self_hit = hermes.invoke_peer(
        "collect.strategy.query",
        {"mission_name": "laser"},
        callee_id="aidata.hermes",
        caller="aidata.hermes",
        client=pair["client"],
    )
    assert self_hit["ready"] is False
    assert "自己" in self_hit["meta"]["message"]

    peer = hermes.invoke_peer(
        "collect.strategy.query",
        {"mission_name": "laser", "trace_id": "hermes-peer"},
        callee_id="aidata.hermes",
        caller="lab.inspector",
        client=pair["client"],
    )
    assert peer["ready"] is True
    assert peer["result"]["items"][0]["mission_name"] == "laser"
    assert "ticket" not in peer["result"]
    assert peer["result"]["_ticket"]["callee_id"] == "aidata.hermes"


def test_client_search_workspace(pair):
    found = pair["client"].search(workspace="ecovacs.aidata")
    assert found["count"] >= 1
    assert found["items"][0]["agent_id"] == "aidata.hermes"
    empty = pair["client"].search(workspace="no.such.space")
    assert empty["count"] == 0


def test_hermes_discover_workspace_and_self_via_search(pair, monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    by_ws = hermes.discover(workspace="ecovacs.aidata", client=pair["client"])
    assert by_ws["ready"] is True
    assert by_ws["items"][0]["agent_id"] == "aidata.hermes"

    self_via_search = hermes.invoke_peer(
        "collect.strategy.query",
        {"mission_name": "laser"},
        caller="aidata.hermes",
        client=pair["client"],
    )
    assert self_via_search["ready"] is False
    assert "自己" in self_via_search["meta"]["message"]
