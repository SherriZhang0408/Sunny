"""CLI: python3 -m sunny_client --skill collect.strategy.query --slots '{"mission_name":"living_room"}'"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import SunnyClient


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Search a skill and invoke it through SUNNY")
    parser.add_argument("--registry", default=os.environ.get("SUNNY_REGISTRY_URL", "http://127.0.0.1:8088"))
    parser.add_argument("--skill", required=True)
    parser.add_argument("--slots", default="{}")
    parser.add_argument("--callee", default="")
    parser.add_argument(
        "--caller",
        default=os.environ.get("SUNNY_CALLER_ID", "lab.inspector"),
        help="caller agent_id when using an admin token",
    )
    args = parser.parse_args(argv)
    slots = json.loads(args.slots)
    client = SunnyClient(
        args.registry,
        agent_key=os.environ.get("SUNNY_AGENT_KEY") or None,
        admin_token=os.environ.get("SUNNY_ADMIN_TOKEN") or "sunny-dev-admin",
    )
    try:
        result = client.invoke(
            args.skill,
            slots,
            callee_id=args.callee or None,
            caller_id=args.caller or None,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
