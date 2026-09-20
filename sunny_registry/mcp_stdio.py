"""Stdio MCP proxy: other agents can hang this process instead of POSTing /mcp.

Env:
  SUNNY_REGISTRY_URL   Registry base, default http://127.0.0.1:8088
  SUNNY_AGENT_KEY      sak_ service key (sent as X-Sunny-Agent-Key)
  SUNNY_AGENT_KEY_FILE Optional path to the key; paths containing scratch are rejected
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional, Tuple

import httpx

DEFAULT_REGISTRY = "http://127.0.0.1:8088"


def encode_message(payload: Dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header = "Content-Length: {0}\r\n\r\n".format(len(raw)).encode("ascii")
    return header + raw


def decode_buffer(buffer: bytes) -> Tuple[Optional[Dict[str, Any]], bytes]:
    sep = buffer.find(b"\r\n\r\n")
    if sep < 0:
        return None, buffer
    headers = buffer[:sep].decode("ascii", errors="replace")
    length = None
    for line in headers.split("\r\n"):
        if line.lower().startswith("content-length:"):
            try:
                length = int(line.split(":", 1)[1].strip())
            except ValueError:
                return None, b""
    if length is None:
        return None, buffer[sep + 4 :]
    start = sep + 4
    if len(buffer) < start + length:
        return None, buffer
    body = buffer[start : start + length]
    rest = buffer[start + length :]
    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError:
        return None, rest
    if not isinstance(payload, dict):
        return None, rest
    return payload, rest


def load_agent_key() -> str:
    key = (os.environ.get("SUNNY_AGENT_KEY") or "").strip()
    path = (os.environ.get("SUNNY_AGENT_KEY_FILE") or "").strip()
    if path:
        if "scratch" in path.replace("\\", "/").lower():
            raise SystemExit("SUNNY_AGENT_KEY_FILE must not be under scratch")
        key = open(path, "r", encoding="utf-8").read().strip()
    return key


def registry_mcp_url() -> str:
    base = (os.environ.get("SUNNY_REGISTRY_URL") or DEFAULT_REGISTRY).rstrip("/")
    if base.endswith("/mcp"):
        return base
    return base + "/mcp"


def auth_headers(key: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Sunny-Agent-Key"] = key
    return headers


def forward_rpc(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float = 30.0):
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32603, "message": response.text}}
        return response.status_code, body


def serve(stdin=None, stdout=None) -> int:
    key = load_agent_key()
    url = registry_mcp_url()
    headers = auth_headers(key)
    incoming = stdin or sys.stdin.buffer
    outgoing = stdout or sys.stdout.buffer
    buffer = b""
    while True:
        chunk = incoming.read(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            message, buffer = decode_buffer(buffer)
            if message is None:
                break
            status, body = forward_rpc(url, headers, message)
            if message.get("id") is None:
                continue
            if not isinstance(body, dict):
                body = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32603, "message": "invalid registry response"},
                }
            outgoing.write(encode_message(body))
            outgoing.flush()
            del status
    return 0


def main() -> None:
    raise SystemExit(serve())


if __name__ == "__main__":
    main()
