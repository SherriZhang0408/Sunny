from __future__ import annotations

import json
from pathlib import Path

import pytest

from sunny_adapter.config import AdapterSettings
from sunny_adapter.enroll import EnrollError, enroll, load_card


ROOT = Path(__file__).resolve().parents[1]


class _Res(object):
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _ScriptClient(object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self.responses.pop(0)


def _settings(tmp_path) -> AdapterSettings:
    settings = AdapterSettings()
    settings.card_path = ROOT / "cards" / "lab.echo.sample.json"
    settings.agent_id = "lab.echo"
    settings.public_url = "http://127.0.0.1:8093/sunny/v1"
    settings.registry_url = "http://registry"
    settings.enroll_token = "enroll-test"
    settings.admin_token = "admin-test"
    settings.key_path = tmp_path / "echo.key"
    settings.agent_key = ""
    settings.enrollment_source = "self"
    return settings


def test_load_card_rewrites_interface_url(tmp_path):
    settings = _settings(tmp_path)
    card = load_card(settings)
    assert card["supportedInterfaces"][0]["url"] == settings.public_url
    assert card["x-sunny"]["lifecycle"] == "registered"


def test_enroll_self_register_writes_key(tmp_path):
    settings = _settings(tmp_path)
    client = _ScriptClient([_Res(200, {"agent_key": "sak_new"})])
    info = enroll(settings, client)
    assert info["mode"] == "self"
    assert settings.key_path.read_text(encoding="utf-8").strip() == "sak_new"
    assert client.calls[0][0] == "POST"
    assert client.calls[0][1].endswith("/api/v1/agents")


def test_enroll_heartbeat_reuse_existing_key(tmp_path):
    settings = _settings(tmp_path)
    settings.key_path.write_text("sak_old\n", encoding="utf-8")
    client = _ScriptClient([_Res(200, {"ok": True}), _Res(200, {"ok": True})])
    info = enroll(settings, client)
    assert info["mode"] == "heartbeat"
    assert info["agent_key"] == "sak_old"


def test_enroll_attach_after_conflict(tmp_path):
    settings = _settings(tmp_path)
    client = _ScriptClient(
        [
            _Res(409, {"detail": "already"}),
            _Res(200, {"agent_key": "sak_attach"}),
            _Res(200, {"ok": True}),
            _Res(200, {"ok": True}),
        ]
    )
    info = enroll(settings, client)
    assert info["mode"] == "attach"
    assert info["agent_key"] == "sak_attach"
    methods = [item[0] for item in client.calls]
    assert methods == ["POST", "POST", "PUT", "POST"]


def test_enroll_raises_on_unexpected_register_error(tmp_path):
    settings = _settings(tmp_path)
    client = _ScriptClient([_Res(500, {"detail": "boom"})])
    with pytest.raises(EnrollError) as exc:
        enroll(settings, client)
    assert "self-register" in str(exc.value)
    assert "500" in str(exc.value)
