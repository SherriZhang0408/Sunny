"""python3 -m sunny_adapter"""

from __future__ import annotations

import uvicorn

from .app import create_adapter_app
from .config import AdapterSettings


def main() -> None:
    settings = AdapterSettings()
    uvicorn.run(
        create_adapter_app(settings, auto_enroll=True),
        host=settings.listen_host,
        port=settings.listen_port,
    )


if __name__ == "__main__":
    main()
