"""Validate invoke slots against the Card skill input_schema."""

from __future__ import annotations

from typing import Any, Dict, Optional

from jsonschema import Draft7Validator


class SlotError(ValueError):
    pass


def skill_input_schema(card: Dict[str, Any], skill_id: str) -> Optional[Dict[str, Any]]:
    for skill in card.get("skills") or []:
        if skill.get("id") == skill_id:
            ext = skill.get("x-sunny") or {}
            schema = ext.get("input_schema")
            return schema if isinstance(schema, dict) else None
    return None


def validate_slots(card: Dict[str, Any], skill_id: str, slots: Dict[str, Any]) -> None:
    schema = skill_input_schema(card, skill_id)
    if not schema:
        return
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(slots), key=lambda item: list(item.path))
    if not errors:
        return
    first = errors[0]
    path = ".".join(str(part) for part in first.absolute_path)
    prefix = "slots.{0}: ".format(path) if path else "slots: "
    raise SlotError(prefix + first.message)
