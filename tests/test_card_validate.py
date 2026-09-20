from __future__ import annotations

import json
from pathlib import Path

from sunny_registry.card_validate import extract_agent_id, scan_secrets, validate_card

ROOT = Path(__file__).resolve().parents[1]


def _sample() -> dict:
    return json.loads((ROOT / "cards" / "aidata.hermes.sample.json").read_text(encoding="utf-8"))


def test_validate_rejects_non_object():
    assert validate_card([]) == ["card must be a JSON object"]
    assert validate_card("nope") == ["card must be a JSON object"]


def test_echo_and_inspector_cards_valid():
    echo = json.loads((ROOT / "cards" / "lab.echo.sample.json").read_text(encoding="utf-8"))
    assert validate_card(echo) == []
    assert extract_agent_id(echo) == "lab.echo"


def test_forbidden_key_and_secret_like_value():
    card = _sample()
    card["x-sunny"]["api_key"] = "not-a-secret-name-only"
    errors = scan_secrets(card)
    assert any("forbidden property name" in item and "api_key" in item for item in errors)

    card = _sample()
    card["description"] = "Authorization: Bearer abcdefghijklmnopqr"
    errors = scan_secrets(card)
    assert any("secret-like value" in item for item in errors)


def test_allowed_exact_values_are_not_secrets():
    card = _sample()
    card["x-sunny"]["invoke_auth"] = "bearer"
    assert scan_secrets(card) == []


def test_write_skill_requires_restricted():
    card = _sample()
    card["skills"][0]["x-sunny"]["side_effects"] = "write"
    card["skills"][0]["x-sunny"]["data_class"] = "internal"
    errors = validate_card(card)
    assert any("requires data_class=restricted" in item for item in errors)


def test_missing_required_fields():
    errors = validate_card({"name": "bare"})
    assert any("missing required field: skills" in item for item in errors)
    assert any("x-sunny missing agent_id" in item for item in errors)
    assert extract_agent_id({}) == ""
