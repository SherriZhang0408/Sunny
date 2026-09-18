"""Sidecar skill handlers. Ticket already authorized the call."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AdapterSettings

CATALOG_PATH = Path(__file__).resolve().parent / "catalog" / "strategies.json"


def _trace(slots: dict) -> str:
    return str(slots.get("trace_id") or "sid-{0}".format(uuid.uuid4().hex[:12]))


def load_strategies() -> List[dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def query_strategy(slots: dict) -> Dict[str, Any]:
    query = (slots.get("query") or "").strip().lower()
    mission = (slots.get("mission_name") or "").strip()
    product = (slots.get("product_line") or "").strip()
    include = slots.get("include_subscenes", True)
    if not query and not mission:
        raise ValueError("query or mission_name required")

    items = []
    for row in load_strategies():
        if product and row.get("product_line") != product:
            continue
        name = row["mission_name"]
        blob = " ".join(
            [
                name,
                row.get("title") or "",
                row.get("description") or "",
                row.get("subscene_field") or "",
            ]
        ).lower()
        if mission and name != mission:
            continue
        if query and query not in blob and query not in name:
            continue
        item = dict(row)
        if not include:
            item["subscene_enums"] = []
            item["subscene_field"] = ""
        items.append(item)

    return {
        "ready": True,
        "mock": False,
        "trace_id": _trace(slots),
        "items": items,
    }


def _try_aidata_count(settings: AdapterSettings, slots: dict) -> Optional[Dict[str, Any]]:
    adapter = settings.aidata_root / "skills" / "adapters" / "es_query_ai_collect.py"
    if not adapter.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("es_query_ai_collect", str(adapter))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None

    filters = []
    if slots.get("mission_name"):
        filters.append(("mission_name", str(slots["mission_name"])))
    if slots.get("quest_name"):
        filters.append(("quest_name", str(slots["quest_name"])))
    if slots.get("sn"):
        filters.append(("meta.sn", str(slots["sn"])))
    robots = slots.get("robotType") or []
    if isinstance(robots, list) and robots:
        filters.append(("robotType", ",".join(str(x) for x in robots)))
    date = slots.get("compute_date") or {}
    if isinstance(date, dict) and date.get("from") and date.get("to"):
        filters.append(("computeDate", "{0}..{1}".format(date["from"], date["to"])))
    if not filters:
        raise ValueError("at least one volume filter required")

    try:
        result = module.run(action="count", filters=filters, confirm=True)
    except Exception as exc:
        return {
            "ready": False,
            "mock": True,
            "count": 0,
            "es_index": "ai_collect",
            "filters_echo": slots,
            "trace_id": _trace(slots),
            "message": "aidata adapter unavailable: {0}".format(exc),
        }
    return {
        "ready": bool(result.get("ready")),
        "mock": bool(result.get("mock")),
        "count": int(result.get("count") or 0),
        "es_index": "ai_collect",
        "filters_echo": {k: v for k, v in slots.items() if k != "trace_id"},
        "trace_id": _trace(slots),
        "message": (result.get("meta") or {}).get("message") or "",
    }


def query_volume(slots: dict, settings: AdapterSettings) -> Dict[str, Any]:
    useful = any(slots.get(k) for k in ("mission_name", "quest_name", "robotType", "compute_date"))
    if not useful:
        raise ValueError("at least one of mission_name, quest_name, robotType, compute_date required")
    live = _try_aidata_count(settings, slots)
    if live is not None:
        return live
    return {
        "ready": False,
        "mock": True,
        "count": 0,
        "es_index": "ai_collect",
        "filters_echo": {k: v for k, v in slots.items() if k != "trace_id"},
        "trace_id": _trace(slots),
        "message": "AIDATA proxy not configured; sidecar did not POST. Ticket accepted, no row data.",
    }


def dispatch(skill_id: str, slots: dict, settings: AdapterSettings) -> Dict[str, Any]:
    if skill_id == "collect.strategy.query":
        return query_strategy(slots)
    if skill_id == "collect.volume.query":
        return query_volume(slots, settings)
    raise KeyError(skill_id)
