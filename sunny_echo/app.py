"""In-process echo HTTP. Not on the Registry data path."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel


class EchoBody(BaseModel):
    q: Optional[str] = None
    query: Optional[str] = None
    trace_id: Optional[str] = None


def create_echo_app() -> FastAPI:
    app = FastAPI(title="SUNNY Echo", version="0.1.0")

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"ok": True, "service": "sunny-echo", "ready": True}

    @app.post("/v1/echo")
    def echo(body: EchoBody) -> Dict[str, Any]:
        query = body.query if body.query not in (None, "") else (body.q or "")
        return {
            "ready": True,
            "query": query,
            "trace_id": body.trace_id or "",
        }

    return app
