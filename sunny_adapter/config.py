from __future__ import annotations

import os
from pathlib import Path

from sunny_registry.net import advertise_host

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


class AdapterSettings:
    def __init__(self) -> None:
        self.registry_url = _env("SUNNY_REGISTRY_URL", "http://127.0.0.1:8088").rstrip("/")
        self.listen_host = _env("SUNNY_ADAPTER_HOST", "0.0.0.0")
        self.listen_port = int(_env("SUNNY_ADAPTER_PORT", "8091"))
        self.public_url = _env(
            "SUNNY_ADAPTER_PUBLIC_URL",
            "http://{0}:{1}/sunny/v1".format(
                advertise_host(self.listen_host),
                self.listen_port,
            ),
        ).rstrip("/")
        self.card_path = Path(_env("SUNNY_ADAPTER_CARD", str(ROOT / "cards" / "aidata.hermes.sample.json")))
        self.agent_id = _env("SUNNY_ADAPTER_AGENT_ID", "aidata.hermes")
        self.admin_token = _env("SUNNY_ADMIN_TOKEN", "sunny-dev-admin")
        self.enroll_token = _env("SUNNY_ENROLL_TOKEN", "sunny-dev-enroll")
        self.agent_key = _env("SUNNY_AGENT_KEY", "")
        self.key_path = Path(_env("SUNNY_ADAPTER_KEY_FILE", str(ROOT / "data" / "adapter-keys" / (self.agent_id + ".key"))))
        self.heartbeat_s = int(_env("SUNNY_ADAPTER_HEARTBEAT_S", "30"))
        self.aidata_root = Path(_env("AIDATA_ROOT", "/home/zhangshuang/PycharmProjects/AIDataAgent"))
        self.enrollment_source = _env("SUNNY_ADAPTER_ENROLLMENT", "self")
