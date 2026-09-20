"""Runtime settings. Tokens stay in env, never in Card JSON."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


class Settings:
    def __init__(self) -> None:
        self.db_path = Path(_env("SUNNY_DB", str(ROOT / "data" / "sunny.db")))
        self.admin_token = _env("SUNNY_ADMIN_TOKEN", "sunny-dev-admin")
        self.developer_password = _env("SUNNY_DEVELOPER_PASSWORD", "sunny-dev-developer")
        self.enroll_token = _env("SUNNY_ENROLL_TOKEN", "sunny-dev-enroll")
        self.ticket_secret = _env("SUNNY_TICKET_SECRET", "sunny-dev-ticket")
        self.ticket_ttl_s = int(_env("SUNNY_TICKET_TTL_S", "300"))
        self.session_ttl_s = int(_env("SUNNY_SESSION_TTL_S", "43200"))
        self.heartbeat_stale_s = int(_env("SUNNY_HEARTBEAT_STALE_S", "90"))
        self.probe_timeout_s = float(_env("SUNNY_PROBE_TIMEOUT_S", "2"))
        self.pull_timeout_s = float(_env("SUNNY_PULL_TIMEOUT_S", "5"))
        self.sweep_s = float(_env("SUNNY_SWEEP_S", "0" if os.environ.get("PYTEST_CURRENT_TEST") else "60"))
        self.refresh_interval_s = float(_env("SUNNY_REFRESH_INTERVAL_S", "300"))
        self.http_transport = None
        self.seed_on_empty = _env("SUNNY_SEED", "1") != "0"
        self.listen_host = _env("SUNNY_HOST", "0.0.0.0")
        self.listen_port = int(_env("SUNNY_PORT", "8088"))
        self.public_url = _env("SUNNY_PUBLIC_URL", "")


def get_settings() -> Settings:
    return Settings()
