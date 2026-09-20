"""python3 -m sunny_echo — default :8092."""

from __future__ import annotations

import os

import uvicorn

from .app import create_echo_app


def main() -> None:
    host = os.environ.get("SUNNY_ECHO_HOST") or "0.0.0.0"
    port = int(os.environ.get("SUNNY_ECHO_PORT") or "8092")
    uvicorn.run(create_echo_app(), host=host, port=port)


if __name__ == "__main__":
    main()
