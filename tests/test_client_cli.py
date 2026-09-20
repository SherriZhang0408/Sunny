from __future__ import annotations

import json

from sunny_client import SunnyClient, invoke_url
from sunny_client.__main__ import main


def test_invoke_url_joins_base_and_skill_path():
    card = {
        "supportedInterfaces": [{"url": "http://sidecar:8091/sunny/v1"}],
        "skills": [
            {
                "id": "echo.ping",
                "x-sunny": {"invoke": {"path": "/sunny/invoke/echo.ping"}},
            }
        ],
    }
    assert invoke_url(card, "echo.ping") == "http://sidecar:8091/sunny/invoke/echo.ping"


def test_invoke_url_requires_interface():
    try:
        invoke_url({"skills": []}, "echo.ping")
    except ValueError as exc:
        assert "supportedInterfaces" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_rejects_bad_slots(capsys):
    assert main(["--skill", "echo.ping", "--slots", "not-json"]) == 1
    err = capsys.readouterr().err
    assert err


def test_cli_rejects_non_object_slots(capsys):
    assert main(["--skill", "echo.ping", "--slots", "[1,2]"]) == 1
    err = capsys.readouterr().err
    assert "object" in err.lower() or "slots" in err.lower()


class _BoomClient(SunnyClient):
    def invoke(self, *args, **kwargs):
        raise RuntimeError("no registered agent offers echo.ping")


def test_cli_prints_invoke_error(monkeypatch, capsys):
    monkeypatch.setattr("sunny_client.__main__.SunnyClient", _BoomClient)
    assert main(["--skill", "echo.ping", "--slots", json.dumps({"query": "hi"})]) == 1
    assert "no registered agent" in capsys.readouterr().err
