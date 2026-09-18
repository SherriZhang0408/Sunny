"""python3 -m sunny_registry — bind 0.0.0.0 so LAN peers can reach Hub."""

from __future__ import annotations

import uvicorn

from .app import create_app
from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.listen_host,
        port=settings.listen_port,
    )


if __name__ == "__main__":
    main()
