from __future__ import annotations

import sqlite3

from sunny_registry.db import connect, migrate
from sunny_registry.store import parse_iso, utcnow


OLD_AGENTS = """
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    version TEXT NOT NULL,
    card_json TEXT NOT NULL,
    enrollment_source TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    last_heartbeat_at TEXT,
    agent_key_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def test_migrate_adds_governance_and_probe_columns(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_AGENTS)
    conn.execute(
        """
        INSERT INTO agents(
            agent_id, workspace, name, description, version, card_json,
            enrollment_source, lifecycle, agent_key_hash, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "lab.legacy",
            "ecovacs.lab",
            "旧卡",
            "升级前的行",
            "0.1.0",
            '{"x-sunny":{"discovery":"approval_required"}}',
            "hub",
            "registered",
            "hash",
            utcnow(),
            utcnow(),
        ),
    )
    conn.commit()
    migrate(conn)
    names = {row["name"] for row in conn.execute("PRAGMA table_info(agents)")}
    for column in (
        "created_by",
        "discovery",
        "probe_ok",
        "probe_category",
        "card_source_url",
        "approval_status",
        "approval_reason",
        "collab_scope",
    ):
        assert column in names
    row = conn.execute("SELECT * FROM agents WHERE agent_id='lab.legacy'").fetchone()
    assert row["created_by"] == "usr_admin"
    assert row["discovery"] == "approval_required"
    assert row["approval_status"] == "pending"
    assert conn.execute("SELECT 1 FROM agent_fts LIMIT 0") is not None
    conn.close()


def test_connect_creates_parent_and_fts(tmp_path):
    db = tmp_path / "nested" / "sunny.db"
    conn = connect(db)
    assert db.is_file()
    assert conn.execute("SELECT 1 FROM users LIMIT 0") is not None
    conn.close()


def test_parse_iso_roundtrip_and_empty():
    now = utcnow()
    parsed = parse_iso(now)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parse_iso("") is None
    assert parse_iso(None) is None
