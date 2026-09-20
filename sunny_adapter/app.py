"""Sidecar HTTP: health + skill invoke. Registry is not on the data path."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from sunny_registry.a2a_export import CACHE_PUBLIC, cached_json, card_etag

from .config import AdapterSettings
from .enroll import enroll, load_card
from .invoke import invoke_skill
from .mapping import MappingError, load_mapping
from .proxy import probe_downstream
from .slots import SlotError


class InvokeBody(BaseModel):
    slots: Dict[str, Any] = {}
    trace_id: Optional[str] = None


def _verify_ticket(settings: AdapterSettings, client: httpx.Client, token: str, skill_id: str) -> dict:
    res = client.post(
        "{0}/api/v1/tickets/verify".format(settings.registry_url),
        headers={"X-Sunny-Agent-Key": settings.agent_key},
        json={"ticket": token, "callee_id": settings.agent_id, "skill_id": skill_id},
    )
    if res.status_code != 200:
        detail = res.text
        try:
            detail = res.json().get("detail") or detail
        except Exception:
            pass
        raise HTTPException(status_code=res.status_code, detail=detail)
    return res.json()["payload"]


def create_adapter_app(
    settings: Optional[AdapterSettings] = None,
    registry_client: Optional[httpx.Client] = None,
    upstream_client: Optional[httpx.Client] = None,
    auto_enroll: bool = False,
) -> FastAPI:
    settings = settings or AdapterSettings()
    owns = registry_client is None
    client = registry_client or httpx.Client(timeout=15.0)
    owns_upstream = upstream_client is None
    upstream = upstream_client or httpx.Client(timeout=15.0)
    stop = threading.Event()

    def beat() -> None:
        if not settings.agent_key:
            return
        try:
            client.post(
                "{0}/api/v1/agents/{1}/heartbeat".format(settings.registry_url, settings.agent_id),
                headers={"X-Sunny-Agent-Key": settings.agent_key},
            )
        except Exception:
            pass
        if not stop.is_set():
            timer = threading.Timer(settings.heartbeat_s, beat)
            timer.daemon = True
            timer.start()
            app.state.timer = timer

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if auto_enroll:
            info = enroll(settings, client)
            settings.agent_key = info["agent_key"]
            beat()
        yield
        stop.set()
        timer = getattr(app.state, "timer", None)
        if timer:
            timer.cancel()
        if owns:
            client.close()
        if owns_upstream:
            upstream.close()

    app = FastAPI(title="SUNNY Adapter", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = client
    app.state.upstream = upstream

    @app.get("/health")
    def health() -> Dict[str, Any]:
        payload = {
            "ok": True,
            "service": "sunny-adapter",
            "agent_id": settings.agent_id,
            "enrolled": bool(settings.agent_key),
            "mapping": None,
            "downstream": {"configured": False},
        }
        if settings.mapping_path and settings.mapping_path.is_file():
            try:
                mapping = load_mapping(settings.mapping_path, settings.agent_id)
            except MappingError as exc:
                payload["mapping"] = {"ok": False, "error": str(exc)}
                return payload
            payload["mapping"] = {
                "ok": True,
                "path": str(settings.mapping_path),
                "routes": [route["skill_id"] for route in mapping.get("routes") or []],
            }
            hb = (mapping.get("heartbeat") or {}).get("url")
            if hb:
                payload["downstream"] = probe_downstream(hb, upstream)
        return payload

    def _sunny_card(request: Request):
        card = load_card(settings)
        return cached_json(request, card, card_etag(card), CACHE_PUBLIC)

    @app.get("/.well-known/agent-card.json")
    def well_known_agent_card(request: Request):
        return _sunny_card(request)

    @app.get("/.well-known/agent.json")
    def well_known_agent_json(request: Request):
        return _sunny_card(request)

    @app.get("/sunny/v1/card")
    def public_card(request: Request):
        return _sunny_card(request)

    @app.post("/sunny/invoke/{skill_id}")
    def invoke(
        skill_id: str,
        body: InvokeBody,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="sunny ticket required")
        if not settings.agent_key:
            raise HTTPException(status_code=503, detail="adapter not enrolled")
        token = authorization.split(" ", 1)[1].strip()
        _verify_ticket(settings, client, token, skill_id)
        slots = dict(body.slots or {})
        if body.trace_id and not slots.get("trace_id"):
            slots["trace_id"] = body.trace_id
        try:
            return invoke_skill(skill_id, slots, settings, upstream=upstream)
        except KeyError:
            raise HTTPException(status_code=404, detail="skill not hosted: {0}".format(skill_id))
        except SlotError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except MappingError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return app


def create_app() -> FastAPI:
    return create_adapter_app(auto_enroll=True)


app = create_app()
