from __future__ import annotations

import httpx
import pytest

from sunny_adapter.mapping import MappingError
from sunny_adapter.proxy import forward, probe_downstream


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_forward_rejects_non_http_url():
    with pytest.raises(MappingError):
        forward({"url": "file:///etc/passwd"}, {"query": "x"}, "echo.ping", httpx.Client())


def test_forward_maps_json_and_ready_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json_loads(request)
        assert body["q"] == "hello"
        return httpx.Response(200, json={"ready": True, "echo": body["q"]})

    out = forward(
        {"url": "http://echo.internal/v1/echo", "map": {"q": "$.slots.query"}},
        {"query": "hello", "trace_id": "t-1"},
        "echo.ping",
        _client(handler),
    )
    assert out["ready"] is True
    assert out["echo"] == "hello"
    assert out["trace_id"] == "t-1"


def test_forward_wraps_plain_json_and_http_errors():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["a", "b"])

    wrapped = forward({"url": "http://echo.internal/v1"}, {}, "echo.ping", _client(ok))
    assert wrapped["ready"] is True
    assert wrapped["data"] == ["a", "b"]

    def bad(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="down")

    failed = forward({"url": "http://echo.internal/v1"}, {}, "echo.ping", _client(bad))
    assert failed["ready"] is False
    assert "502" in failed["message"]

    def not_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="plain")

    empty = forward({"url": "http://echo.internal/v1"}, {}, "echo.ping", _client(not_json))
    assert empty["ready"] is True
    assert empty["data"] is None


def test_forward_upstream_transport_error():
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=_request)

    out = forward({"url": "http://echo.internal/v1"}, {}, "echo.ping", _client(boom))
    assert out["ready"] is False
    assert out["message"] == "upstream request failed"


def test_probe_downstream_ok_and_unreachable():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    assert probe_downstream("http://echo.internal/health", _client(handler))["ok"] is True
    bad = probe_downstream("not-a-url", httpx.Client())
    assert bad["ok"] is False
    assert bad["configured"] is True


def json_loads(request: httpx.Request):
    import json

    return json.loads(request.content.decode("utf-8"))
