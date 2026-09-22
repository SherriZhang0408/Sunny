"""Validate a SUNNY Agent Card: JSON Schema + no-secret scan."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "sunny-card.schema.json"

FORBIDDEN_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|"
    r"connection[_-]?string|private[_-]?key|access[_-]?key)",
    re.I,
)
SECRET_VALUE = re.compile(
    r"(?:"
    r"bearer\s+[A-Za-z0-9._\-+=/]{16,}"
    r"|jdbc:"
    r"|mongodb(?:\+srv)?://"
    r"|[a-z]+://[^/\s:]+:[^/\s@]+@"
    r"|AKIA[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"
    r")",
    re.I,
)
ALLOWED_EXACT_VALUES = {"bearer", "sunny-ticket", "sunny_ticket"}


def walk(node: Any, path: str = "$") -> Iterable[Tuple[str, str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            child = "{0}.{1}".format(path, key)
            yield "key", child, key
            yield from walk(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, "{0}[{1}]".format(path, index))
    else:
        yield "value", path, node


def scan_secrets(card: Any) -> List[str]:
    errors = []
    for kind, path, raw in walk(card):
        text = raw if isinstance(raw, str) else ""
        if kind == "key" and FORBIDDEN_KEY.search(text):
            errors.append("forbidden property name at {0}: {1}".format(path, text))
        if kind == "value" and isinstance(raw, str):
            if text.strip().lower() in ALLOWED_EXACT_VALUES:
                continue
            if SECRET_VALUE.search(text):
                errors.append("secret-like value at {0}".format(path))
    return errors


def structural_checks(card: dict) -> List[str]:
    errors = []
    for field in (
        "name",
        "description",
        "version",
        "supportedInterfaces",
        "capabilities",
        "defaultInputModes",
        "defaultOutputModes",
        "skills",
        "x-sunny",
    ):
        if field not in card:
            errors.append("missing required field: {0}".format(field))
    if not card.get("supportedInterfaces"):
        errors.append("supportedInterfaces must have at least 1 item")
    skills = card.get("skills") or []
    if not skills:
        errors.append("skills must have at least 1 item")
    for index, skill in enumerate(skills):
        if not isinstance(skill, dict):
            errors.append("skills[{0}] is not an object".format(index))
            continue
        for field in ("id", "name", "description", "tags", "x-sunny"):
            if field not in skill:
                errors.append("skills[{0}] missing {1}".format(index, field))
        ext = skill.get("x-sunny") or {}
        if isinstance(ext, dict):
            for field in ("data_class", "side_effects", "input_schema", "output_schema"):
                if field not in ext:
                    errors.append("skills[{0}].x-sunny missing {1}".format(index, field))
            if ext.get("side_effects") in {"write", "execute_sql"} and ext.get("data_class") != "restricted":
                errors.append(
                    "skills[{0}] side_effects={1} requires data_class=restricted".format(
                        index, ext.get("side_effects")
                    )
                )
    sunny = card.get("x-sunny") or {}
    if isinstance(sunny, dict):
        for field in (
            "agent_id",
            "workspace",
            "discovery",
            "access_tier",
            "lifecycle",
            "not_exposed",
            "invoke_auth",
            "invoke_identity",
            "scratch_access",
        ):
            if field not in sunny:
                errors.append("x-sunny missing {0}".format(field))
        if not sunny.get("not_exposed"):
            errors.append("x-sunny.not_exposed must list at least one internal capability")
        if "scope" in sunny and sunny.get("scope") not in {"household", "cohort"}:
            errors.append("x-sunny.scope must be household or cohort")
    return errors


def schema_errors(card: dict) -> List[str]:
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return ["jsonschema Draft7Validator unavailable"]

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    errors = []
    for err in validator.iter_errors(card):
        path = ".".join(str(p) for p in err.absolute_path) or "$"
        errors.append("{0}: {1}".format(path, err.message))
    return errors


def validate_card(card: Any) -> List[str]:
    if not isinstance(card, dict):
        return ["card must be a JSON object"]
    return structural_checks(card) + scan_secrets(card) + schema_errors(card)


def extract_agent_id(card: dict) -> str:
    return str((card.get("x-sunny") or {}).get("agent_id") or "").strip()
