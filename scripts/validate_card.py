#!/usr/bin/env python3
"""Validate a SUNNY Agent Card: JSON Schema + no-secret scan."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sunny_registry.card_validate import validate_card  # noqa: E402


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: python3 scripts/validate_card.py <card.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print("file not found: {0}".format(path), file=sys.stderr)
        return 2
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print("invalid JSON: {0}".format(exc), file=sys.stderr)
        return 1
    errors = validate_card(card)
    if errors:
        print("FAIL {0} ({1} error(s))".format(path, len(errors)))
        for item in errors:
            print("  - {0}".format(item))
        return 1
    print("OK {0}".format(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
