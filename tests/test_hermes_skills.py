from __future__ import annotations

from pathlib import Path

import pytest

from sunny_client import hermes


class FakeClient:
    def __init__(self, items=None, invoke_result=None, search_error=None, invoke_error=None):
        self.closed = False
        self.searches = []
        self.invokes = []
        self.search_error = search_error
        self.invoke_error = invoke_error
        self.cards = {
            "chatbi.gateway": {
                "agent_id": "chatbi.gateway",
                "name": "ChatBI",
                "description": "问数",
                "version": "0.1.0",
                "workspace": "ecovacs.bi",
                "lifecycle": "registered",
                "discovery": "registered_peers",
                "runtime_status": "online",
                "access_tier": "internal",
                "skill_count": 1,
                "skills": [{"id": "bi.template.run", "name": "模板", "tags": ["l1"]}],
                "card": {
                    "supportedInterfaces": [{"url": "http://10.1.2.3:8095/sunny/v1"}],
                    "skills": [{"id": "bi.template.run", "name": "模板", "tags": ["l1"]}],
                },
                "agent_key": "sak_should_not_leak",
                "can_manage": True,
            }
        }
        self._items = items
        self._invoke_result = invoke_result

    def search(self, skill=None, tag=None, q=None, workspace=None):
        self.searches.append(
            {"skill": skill, "tag": tag, "q": q, "workspace": workspace}
        )
        if self.search_error:
            raise self.search_error
        if self._items is not None:
            return {"items": self._items, "count": len(self._items)}
        return {"items": [self.cards["chatbi.gateway"]], "count": 1}

    def get_card(self, agent_id):
        if agent_id not in self.cards:
            raise RuntimeError("agent not found")
        return self.cards[agent_id]

    def invoke(self, skill_id, slots, callee_id=None, caller_id=None):
        self.invokes.append(
            {
                "skill_id": skill_id,
                "slots": slots,
                "callee_id": callee_id,
                "caller_id": caller_id,
            }
        )
        if self.invoke_error:
            raise self.invoke_error
        if self._invoke_result is not None:
            return self._invoke_result
        return {
            "ready": True,
            "mock": False,
            "answer": "ok",
            "ticket": "raw-ticket-must-drop",
            "agent_key": "sak_drop",
            "_ticket": {"jti": "jti-1", "callee_id": callee_id, "ticket": "hidden"},
        }

    def close(self):
        self.closed = True


def test_skills_off_by_default(monkeypatch):
    monkeypatch.delenv("AIDATA_SUNNY", raising=False)
    monkeypatch.delenv("SUNNY_HERMES_SKILLS", raising=False)
    assert hermes.skills_enabled() is False
    out = hermes.discover(client=FakeClient())
    assert out["ready"] is False
    assert out["items"] == []
    assert "默认关闭" in out["meta"]["message"]


@pytest.mark.parametrize("value", ["0", "false", "off", "no", ""])
def test_skills_ignore_falsey_flag(monkeypatch, value):
    monkeypatch.setenv("AIDATA_SUNNY", value)
    monkeypatch.delenv("SUNNY_HERMES_SKILLS", raising=False)
    assert hermes.skills_enabled() is False


def test_skills_enabled_flag(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    assert hermes.skills_enabled() is True
    monkeypatch.delenv("AIDATA_SUNNY", raising=False)
    monkeypatch.setenv("SUNNY_HERMES_SKILLS", "true")
    assert hermes.skills_enabled() is True


def test_key_file_rejects_scratch(tmp_path, monkeypatch):
    monkeypatch.delenv("SUNNY_AGENT_KEY", raising=False)
    scratch = tmp_path / "scratch" / "sunny-agent-key.txt"
    scratch.parent.mkdir()
    scratch.write_text("sak_from_scratch", encoding="utf-8")
    monkeypatch.setenv("SUNNY_AGENT_KEY_FILE", str(scratch))
    with pytest.raises(ValueError, match="scratch"):
        hermes.load_agent_key()


def test_key_file_reads_service_path(tmp_path, monkeypatch):
    monkeypatch.delenv("SUNNY_AGENT_KEY", raising=False)
    key_path = tmp_path / "adapter-keys" / "aidata.hermes.key"
    key_path.parent.mkdir()
    key_path.write_text("sak_service\n", encoding="utf-8")
    monkeypatch.setenv("SUNNY_AGENT_KEY_FILE", str(key_path))
    assert hermes.load_agent_key() == "sak_service"


def test_key_env_wins_over_file(tmp_path, monkeypatch):
    key_path = tmp_path / "adapter-keys" / "aidata.hermes.key"
    key_path.parent.mkdir()
    key_path.write_text("sak_file", encoding="utf-8")
    monkeypatch.setenv("SUNNY_AGENT_KEY", "sak_env")
    monkeypatch.setenv("SUNNY_AGENT_KEY_FILE", str(key_path))
    assert hermes.load_agent_key() == "sak_env"


def test_key_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("SUNNY_AGENT_KEY", raising=False)
    monkeypatch.setenv("SUNNY_AGENT_KEY_FILE", str(tmp_path / "no-such.key"))
    with pytest.raises(ValueError, match="不存在"):
        hermes.load_agent_key()


def test_blocked_local_skills():
    assert hermes.is_blocked_skill("es.query_ai_collect")
    assert hermes.is_blocked_skill("cvat.create_special_task")
    assert hermes.is_blocked_skill("kb.retrieve")
    assert hermes.is_blocked_skill("image.screen")
    assert hermes.is_blocked_skill("sunny.invoke")
    assert not hermes.is_blocked_skill("bi.template.run")
    assert not hermes.is_blocked_skill("collect.strategy.query")


@pytest.mark.parametrize(
    "skill_id",
    [
        "es-query-ai-collect",
        "ES.query_ai_collect",
        "Cvat-Create-Special-Task",
        "kb-retrieve",
        "working-memory",
        "html-report",
        "session-scratch",
        "label-task-catalog",
    ],
)
def test_blocked_hermes_folder_names_and_case(skill_id):
    assert hermes.is_blocked_skill(skill_id)


def test_discover_sanitizes_card(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient()
    out = hermes.discover(skill="bi.template.run", tag="l1", q="Chat", workspace="ecovacs.bi", client=fake)
    assert out["ready"] is True
    item = out["items"][0]
    assert item["agent_id"] == "chatbi.gateway"
    assert item["skills"][0]["id"] == "bi.template.run"
    assert "agent_key" not in item
    assert "card" not in item
    assert "supportedInterfaces" not in item
    assert "can_manage" not in item
    assert fake.searches[0] == {
        "skill": "bi.template.run",
        "tag": "l1",
        "q": "Chat",
        "workspace": "ecovacs.bi",
    }


def test_discover_by_agent_id_strips_secrets(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    out = hermes.discover(agent_id="chatbi.gateway", client=FakeClient())
    assert out["ready"] is True
    item = out["items"][0]
    assert item["name"] == "ChatBI"
    assert "agent_key" not in item
    assert "card" not in item
    assert "supportedInterfaces" not in item


def test_summarize_card_only_item_drops_url():
    item = hermes.summarize_item(
        {
            "agent_id": "peer.one",
            "card": {
                "name": "Peer",
                "description": "d",
                "version": "1.0.0",
                "supportedInterfaces": [{"url": "http://10.9.8.7:8095/sunny/v1"}],
                "skills": [{"id": "bi.template.run", "name": "T", "tags": ["l1"]}],
                "x-sunny": {"workspace": "ecovacs.bi", "discovery": "registered_peers", "access_tier": "internal"},
            },
        }
    )
    assert item["name"] == "Peer"
    assert item["skills"][0]["id"] == "bi.template.run"
    assert "supportedInterfaces" not in item
    dumped = str(item)
    assert "10.9.8.7" not in dumped


def test_sanitize_drops_raw_ticket_string():
    clean = hermes.sanitize({"_ticket": "eyJhbGciOiJIUzI1NiJ9.raw", "ok": True})
    assert "_ticket" not in clean
    assert clean["ok"] is True


def test_discover_requires_key_when_no_client(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    monkeypatch.delenv("SUNNY_AGENT_KEY", raising=False)
    monkeypatch.delenv("SUNNY_AGENT_KEY_FILE", raising=False)
    out = hermes.discover()
    assert out["ready"] is False
    assert "SUNNY_AGENT_KEY" in out["meta"]["message"]


def test_discover_search_error(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient(search_error=RuntimeError("registry down"))
    out = hermes.discover(q="x", client=fake)
    assert out["ready"] is False
    assert "registry down" in out["meta"]["message"]
    assert fake.closed is False


def test_discover_unknown_agent(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    out = hermes.discover(agent_id="missing.agent", client=FakeClient())
    assert out["ready"] is False
    assert "not found" in out["meta"]["message"]


def test_invoke_blocks_local_skill(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient()
    out = hermes.invoke_peer("es.query_ai_collect", {"mission_name": "living_room"}, client=fake)
    assert out["ready"] is False
    assert fake.invokes == []
    assert "本机技能" in out["meta"]["message"]


def test_invoke_blocks_hyphenated_local_skill(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient()
    out = hermes.invoke_peer("es-query-ai-collect", {}, client=fake)
    assert out["ready"] is False
    assert fake.invokes == []


def test_invoke_blocks_self(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient()
    out = hermes.invoke_peer(
        "bi.template.run",
        {},
        callee_id="aidata.hermes",
        caller="aidata.hermes",
        client=fake,
    )
    assert out["ready"] is False
    assert fake.invokes == []
    assert "自己" in out["meta"]["message"]


def test_invoke_blocks_self_resolved_from_search(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient(items=[{"agent_id": "aidata.hermes", "skills": []}])
    out = hermes.invoke_peer("collect.strategy.query", {}, caller="aidata.hermes", client=fake)
    assert out["ready"] is False
    assert fake.invokes == []
    assert "自己" in out["meta"]["message"]


def test_invoke_empty_skill(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    out = hermes.invoke_peer("  ", {}, client=FakeClient())
    assert out["ready"] is False
    assert "不能为空" in out["meta"]["message"]


def test_invoke_slots_must_be_object(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient()
    out = hermes.invoke_peer("bi.template.run", ["not", "object"], callee_id="chatbi.gateway", client=fake)
    assert out["ready"] is False
    assert "JSON 对象" in out["meta"]["message"]
    assert fake.invokes == []


def test_invoke_no_directory_hit(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient(items=[])
    out = hermes.invoke_peer("bi.template.run", {}, caller="aidata.hermes", client=fake)
    assert out["ready"] is False
    assert "没有提供" in out["meta"]["message"]


def test_invoke_peer_error(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient(invoke_error=RuntimeError("sidecar 502"))
    out = hermes.invoke_peer(
        "bi.template.run",
        {},
        callee_id="chatbi.gateway",
        caller="aidata.hermes",
        client=fake,
    )
    assert out["ready"] is False
    assert "502" in out["meta"]["message"]


def test_invoke_peer_sanitizes_ticket(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient()
    out = hermes.invoke_peer(
        "bi.template.run",
        {"template_id": "t1"},
        callee_id="chatbi.gateway",
        caller="aidata.hermes",
        client=fake,
    )
    assert out["ready"] is True
    assert out["result"]["answer"] == "ok"
    assert "ticket" not in out["result"]
    assert "agent_key" not in out["result"]
    assert out["result"]["_ticket"] == {"jti": "jti-1", "callee_id": "chatbi.gateway"}
    assert out["meta"]["ticket_jti"] == "jti-1"
    assert fake.invokes[0]["callee_id"] == "chatbi.gateway"
    assert fake.closed is False


def test_invoke_passes_ready_false(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    fake = FakeClient(
        invoke_result={"ready": False, "mock": True, "count": 0, "_ticket": {"jti": "j2", "callee_id": "chatbi.gateway"}}
    )
    out = hermes.invoke_peer(
        "bi.template.run",
        {},
        callee_id="chatbi.gateway",
        caller="aidata.hermes",
        client=fake,
    )
    assert out["ready"] is False
    assert out["mock"] is True
    assert out["result"]["_ticket"]["jti"] == "j2"


def test_cli_discover_off(monkeypatch, capsys):
    monkeypatch.delenv("AIDATA_SUNNY", raising=False)
    monkeypatch.delenv("SUNNY_HERMES_SKILLS", raising=False)
    code = hermes.main(["discover", "--skill", "bi.template.run"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "默认关闭" in printed


def test_cli_invoke_bad_json(monkeypatch, capsys):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    code = hermes.main(["invoke", "--skill", "bi.template.run", "--slots", "not-json"])
    assert code == 1
    assert capsys.readouterr().err


def test_cli_invoke_slots_must_be_object(monkeypatch, capsys):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    code = hermes.main(["invoke", "--skill", "bi.template.run", "--slots", "[]"])
    assert code == 1
    assert "JSON object" in capsys.readouterr().err


def test_owned_client_closed_on_error(monkeypatch):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    monkeypatch.setenv("SUNNY_AGENT_KEY", "sak_unit")
    created = []

    class Boom(FakeClient):
        def __init__(self, *args, **kwargs):
            FakeClient.__init__(self, search_error=RuntimeError("boom"))
            created.append(self)

    monkeypatch.setattr(hermes, "SunnyClient", Boom)
    out = hermes.discover(q="x")
    assert out["ready"] is False
    assert created[0].closed is True


def test_is_scratch_path_home():
    assert hermes.is_scratch_path(str(Path.home() / ".hermes" / "scratch" / "sunny-agent-key.txt"))
    assert not hermes.is_scratch_path(str(Path.home() / ".hermes" / "keys" / "sunny.key"))


def test_caller_and_registry_defaults(monkeypatch):
    monkeypatch.delenv("SUNNY_CALLER_ID", raising=False)
    monkeypatch.delenv("SUNNY_REGISTRY_URL", raising=False)
    assert hermes.caller_id() == "aidata.hermes"
    assert hermes.registry_url() == "http://127.0.0.1:8088"
    monkeypatch.setenv("SUNNY_CALLER_ID", "   ")
    assert hermes.caller_id() == "aidata.hermes"
    monkeypatch.setenv("SUNNY_REGISTRY_URL", "http://10.1.2.3:8088/")
    assert hermes.registry_url() == "http://10.1.2.3:8088"


def test_scratch_key_file_becomes_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("AIDATA_SUNNY", "1")
    monkeypatch.delenv("SUNNY_AGENT_KEY", raising=False)
    scratch = tmp_path / "scratch" / "key.txt"
    scratch.parent.mkdir()
    scratch.write_text("sak_x", encoding="utf-8")
    monkeypatch.setenv("SUNNY_AGENT_KEY_FILE", str(scratch))
    out = hermes.discover(q="x")
    assert out["ready"] is False
    assert "scratch" in out["meta"]["message"]
