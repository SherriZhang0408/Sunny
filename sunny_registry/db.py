"""SQLite schema for the registry control plane."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
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
    created_by TEXT,
    discovery TEXT NOT NULL DEFAULT 'registered_peers',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    name TEXT NOT NULL,
    tags_csv TEXT NOT NULL,
    side_effects TEXT NOT NULL,
    data_class TEXT NOT NULL,
    PRIMARY KEY (agent_id, skill_id)
);

CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    rev INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    enrollment_source TEXT,
    card_json TEXT,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    jti TEXT PRIMARY KEY,
    caller_id TEXT NOT NULL,
    callee_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    card_version TEXT,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_id TEXT NOT NULL,
    callee_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    status TEXT NOT NULL,
    trace_id TEXT,
    ticket_jti TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observe_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT NOT NULL,
    caller_id TEXT,
    callee_id TEXT,
    skill_id TEXT,
    trace_id TEXT,
    ticket_jti TEXT,
    summary TEXT NOT NULL,
    detail_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revisions_agent ON revisions(agent_id, rev);
CREATE INDEX IF NOT EXISTS idx_skills_id ON agent_skills(skill_id);
CREATE INDEX IF NOT EXISTS idx_invocations_pair ON invocations(caller_id, callee_id);
CREATE INDEX IF NOT EXISTS idx_observe_created ON observe_events(created_at);
CREATE INDEX IF NOT EXISTS idx_observe_trace ON observe_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_observe_kind ON observe_events(kind);
"""


def _column_names(conn: sqlite3.Connection, table: str) -> set:
    rows = conn.execute("PRAGMA table_info({0})".format(table)).fetchall()
    return {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if "created_by" not in _column_names(conn, "agents"):
        conn.execute("ALTER TABLE agents ADD COLUMN created_by TEXT")
        conn.execute(
            "UPDATE agents SET created_by = 'usr_admin' "
            "WHERE created_by IS NULL AND enrollment_source = 'hub'"
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_created_by ON agents(created_by)")
    if "discovery" not in _column_names(conn, "agents"):
        conn.execute("ALTER TABLE agents ADD COLUMN discovery TEXT")
        rows = conn.execute("SELECT agent_id, card_json FROM agents").fetchall()
        for row in rows:
            card = json.loads(row["card_json"] or "{}")
            value = ((card.get("x-sunny") or {}).get("discovery") or "registered_peers")
            if value not in {"registered_peers", "private", "approval_required"}:
                value = "registered_peers"
            conn.execute("UPDATE agents SET discovery = ? WHERE agent_id = ?", (value, row["agent_id"]))
        conn.execute("UPDATE agents SET discovery = 'registered_peers' WHERE discovery IS NULL")
    if "card_version" not in _column_names(conn, "tickets"):
        conn.execute("ALTER TABLE tickets ADD COLUMN card_version TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_discovery ON agents(discovery)")
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn
