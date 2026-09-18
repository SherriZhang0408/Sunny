"""Register or attach this sidecar to the Registry. Never writes secrets into the Card."""

from __future__ import annotations

import json
from typing import Any, Dict

import httpx

from .config import AdapterSettings


class EnrollError(RuntimeError):
    pass


def load_card(settings: AdapterSettings) -> dict:
    card = json.loads(settings.card_path.read_text(encoding="utf-8"))
    interfaces = card.setdefault("supportedInterfaces", [])
    if interfaces:
        interfaces[0]["url"] = settings.public_url
        interfaces[0]["protocolBinding"] = "HTTP+JSON"
    else:
        interfaces.append(
            {"url": settings.public_url, "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}
        )
    card.setdefault("x-sunny", {})["lifecycle"] = "registered"
    return card


def _read_key(settings: AdapterSettings) -> str:
    if settings.agent_key:
        return settings.agent_key
    if settings.key_path.is_file():
        return settings.key_path.read_text(encoding="utf-8").strip()
    return ""


def _write_key(settings: AdapterSettings, key: str) -> None:
    settings.key_path.parent.mkdir(parents=True, exist_ok=True)
    settings.key_path.write_text(key + "\n", encoding="utf-8")
    settings.agent_key = key


def _raise(res: httpx.Response, action: str) -> None:
    detail = res.text
    try:
        detail = res.json().get("detail") or detail
    except Exception:
        pass
    raise EnrollError("{0} failed ({1}): {2}".format(action, res.status_code, detail))


def enroll(settings: AdapterSettings, client: httpx.Client) -> Dict[str, Any]:
    card = load_card(settings)
    agent_id = settings.agent_id
    key = _read_key(settings)

    if key:
        hb = client.post(
            "{0}/api/v1/agents/{1}/heartbeat".format(settings.registry_url, agent_id),
            headers={"X-Sunny-Agent-Key": key},
        )
        if hb.status_code == 200:
            put = client.put(
                "{0}/api/v1/agents/{1}".format(settings.registry_url, agent_id),
                headers={"X-Sunny-Agent-Key": key},
                json={"card": card},
            )
            if put.status_code == 200:
                return {"agent_id": agent_id, "agent_key": key, "mode": "heartbeat"}
        key = ""

    created = client.post(
        "{0}/api/v1/agents".format(settings.registry_url),
        headers={"X-Sunny-Enroll": settings.enroll_token},
        json={"card": card, "enrollment_source": settings.enrollment_source},
    )
    if created.status_code == 200:
        body = created.json()
        _write_key(settings, body["agent_key"])
        return {"agent_id": agent_id, "agent_key": body["agent_key"], "mode": "self"}

    if created.status_code != 409:
        _raise(created, "self-register")

    minted = client.post(
        "{0}/api/v1/agents/{1}/keys".format(settings.registry_url, agent_id),
        headers={"Authorization": "Bearer {0}".format(settings.admin_token)},
    )
    if minted.status_code != 200:
        _raise(minted, "issue-key")
    key = minted.json()["agent_key"]
    _write_key(settings, key)
    put = client.put(
        "{0}/api/v1/agents/{1}".format(settings.registry_url, agent_id),
        headers={"X-Sunny-Agent-Key": key},
        json={"card": card},
    )
    if put.status_code != 200:
        _raise(put, "update-card")
    client.post(
        "{0}/api/v1/agents/{1}/heartbeat".format(settings.registry_url, agent_id),
        headers={"X-Sunny-Agent-Key": key},
    )
    return {"agent_id": agent_id, "agent_key": key, "mode": "attach"}
