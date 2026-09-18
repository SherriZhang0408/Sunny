"""Load a sidecar mapping file: local handlers or HTTP routes."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import Draft7Validator

ROUTE_SCHEMA = {
    "type": "object",
    "required": ["skill_id"],
    "additionalProperties": False,
    "properties": {
        "skill_id": {"type": "string", "minLength": 1},
        "handler": {"type": "string", "enum": ["local", "http"]},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT"]},
        "url": {"type": "string", "minLength": 1},
        "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 120},
        "headers": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "map": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
    },
}

MAPPING_SCHEMA = {
    "type": "object",
    "required": ["routes"],
    "additionalProperties": False,
    "properties": {
        "agent_id": {"type": "string"},
        "card": {"type": "string"},
        "routes": {"type": "array", "minItems": 1, "items": ROUTE_SCHEMA},
        "heartbeat": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string"},
                "interval_s": {"type": "integer", "minimum": 1, "maximum": 3600},
            },
        },
    },
}

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class MappingError(ValueError):
    pass


def expand_env(text: str, environ: Optional[Dict[str, str]] = None) -> str:
    env = environ if environ is not None else os.environ

    def repl(match: re.Match) -> str:
        name = match.group(1)
        default = match.group(2)
        value = env.get(name)
        if value is None or value == "":
            if default is not None:
                return default
            raise MappingError("unresolved env ${{{0}}}".format(name))
        return value

    return _ENV.sub(repl, text)


def resolve_path(context: Dict[str, Any], expr: str) -> Any:
    path = expr.strip()
    if path.startswith("$."):
        path = path[2:]
    current: Any = context
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def apply_map(slots: Dict[str, Any], skill_id: str, mapping: Optional[Dict[str, str]]) -> Dict[str, Any]:
    context = {"slots": slots, "skill_id": skill_id}
    if not mapping:
        return {"skill_id": skill_id, "slots": slots, "trace_id": slots.get("trace_id")}
    body: Dict[str, Any] = {}
    for dest, expr in mapping.items():
        value = resolve_path(context, expr)
        if value is not None:
            body[dest] = value
    return body


def _load_text(path: Path) -> Dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            raise MappingError("PyYAML is required to read {0}".format(path.name))
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise MappingError("mapping must be an object")
    return data


def load_mapping(path: Path, agent_id: Optional[str] = None) -> Dict[str, Any]:
    data = _load_text(path)
    errors = sorted(Draft7Validator(MAPPING_SCHEMA).iter_errors(data), key=lambda item: list(item.path))
    if errors:
        raise MappingError(errors[0].message)
    if agent_id and data.get("agent_id") and data["agent_id"] != agent_id:
        raise MappingError("mapping agent_id {0} does not match {1}".format(data["agent_id"], agent_id))
    for route in data["routes"]:
        handler = route.get("handler") or ("http" if route.get("url") else "local")
        route["handler"] = handler
        if handler == "http" and not route.get("url"):
            raise MappingError("http route {0} needs url".format(route.get("skill_id")))
        if handler == "local" and route.get("url"):
            raise MappingError("local route {0} cannot have url".format(route.get("skill_id")))
    return data


def route_for(mapping: Optional[Dict[str, Any]], skill_id: str) -> Optional[Dict[str, Any]]:
    if not mapping:
        return None
    for route in mapping.get("routes") or []:
        if route.get("skill_id") == skill_id:
            return route
    return None


def default_mapping_path(root: Path, agent_id: str) -> Path:
    return root / "sunny_adapter" / "mappings" / (agent_id + ".json")
