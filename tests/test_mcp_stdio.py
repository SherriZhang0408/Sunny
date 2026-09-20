from __future__ import annotations

import io
import json

import pytest

from sunny_registry.mcp_stdio import (
    auth_headers,
    decode_buffer,
    encode_message,
    load_agent_key,
    registry_mcp_url,
    serve,
)


def test_decode_partial_and_invalid_frames():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    framed = encode_message(payload)
    assert decode_buffer(framed[:10]) == (None, framed[:10])
    bad_len = b"Content-Length: nope\r\n\r\n{}"
    assert decode_buffer(bad_len) == (None, b"")
    not_obj = b"Content-Length: 2\r\n\r\n[]"
    decoded, rest = decode_buffer(not_obj)
    assert decoded is None
    assert rest == b""


def test_registry_mcp_url_and_auth(monkeypatch):
    monkeypatch.delenv("SUNNY_REGISTRY_URL", raising=False)
    assert registry_mcp_url() == "http://127.0.0.1:8088/mcp"
    monkeypatch.setenv("SUNNY_REGISTRY_URL", "http://hub:8088/mcp")
    assert registry_mcp_url() == "http://hub:8088/mcp"
    headers = auth_headers("sak_x")
    assert headers["X-Sunny-Agent-Key"] == "sak_x"
    assert auth_headers("") == {"Content-Type": "application/json"}


def test_load_agent_key_rejects_scratch(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNNY_AGENT_KEY", "sak_env")
    monkeypatch.delenv("SUNNY_AGENT_KEY_FILE", raising=False)
    assert load_agent_key() == "sak_env"
    key_file = tmp_path / "agent.key"
    key_file.write_text("sak_file\n", encoding="utf-8")
    monkeypatch.delenv("SUNNY_AGENT_KEY", raising=False)
    monkeypatch.setenv("SUNNY_AGENT_KEY_FILE", str(key_file))
    assert load_agent_key() == "sak_file"
    monkeypatch.setenv("SUNNY_AGENT_KEY_FILE", str(tmp_path / "scratch" / "leaked.key"))
    with pytest.raises(SystemExit):
        load_agent_key()


def test_serve_forwards_requests_and_skips_notifications(monkeypatch):
    calls = []

    def fake_forward(url, headers, payload, timeout=30.0):
        calls.append((url, headers, payload))
        return 200, {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"ok": True}}

    monkeypatch.setattr("sunny_registry.mcp_stdio.forward_rpc", fake_forward)
    monkeypatch.setenv("SUNNY_REGISTRY_URL", "http://hub:8088")
    monkeypatch.setenv("SUNNY_AGENT_KEY", "sak_stdio")
    monkeypatch.delenv("SUNNY_AGENT_KEY_FILE", raising=False)

    ping = encode_message({"jsonrpc": "2.0", "id": 3, "method": "ping"})
    note = encode_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    stdin = io.BytesIO(ping + note)
    stdout = io.BytesIO()
    assert serve(stdin=stdin, stdout=stdout) == 0
    assert len(calls) == 2
    decoded, rest = decode_buffer(stdout.getvalue())
    assert decoded["result"]["ok"] is True
    assert rest == b""
