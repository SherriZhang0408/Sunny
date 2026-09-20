"""SQLite FTS5 index for Hub list and peer search ``q``.

Only index agent identity plus **searchable** skills (read + public/internal).
Restricted / write skills stay out of the document so ``q`` cannot leak them.
Ticket gates are unchanged: FTS only decides which cards enter the existing
SQL filters.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SEARCHABLE_DATA_CLASS = {"public", "internal"}

_SPECIAL = re.compile(r"""["'*(){}[\]^~:]+""")
_WS = re.compile(r"\s+")

CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS agent_fts USING fts5(
    agent_id,
    name,
    description,
    skills,
    tokenize = 'unicode61'
)
"""


def ensure_schema(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(CREATE_SQL)
        return True
    except sqlite3.OperationalError:
        return False


def available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1 FROM agent_fts LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False


def _searchable_skills(card: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for skill in card.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        ext = skill.get("x-sunny") or {}
        if (ext.get("side_effects") or "read") != "read":
            continue
        if (ext.get("data_class") or "internal") not in SEARCHABLE_DATA_CLASS:
            continue
        yield skill


def _is_cjk(token: str) -> bool:
    return bool(token) and all("\u4e00" <= ch <= "\u9fff" for ch in token)


def cjk_bigrams(text: str) -> List[str]:
    chars = [ch for ch in text or "" if "\u4e00" <= ch <= "\u9fff"]
    if len(chars) < 2:
        return []
    return ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]


def _skill_blob(card: Dict[str, Any]) -> str:
    parts = []  # type: List[str]
    for skill in _searchable_skills(card):
        skill_id = str(skill.get("id") or "")
        parts.append(skill_id)
        parts.append(skill_id.replace(".", " ").replace("_", " ").replace("-", " "))
        parts.append(str(skill.get("name") or ""))
        parts.append(str(skill.get("description") or ""))
        for tag in skill.get("tags") or []:
            parts.append(str(tag))
        for example in skill.get("examples") or []:
            parts.append(str(example))
    raw = " ".join(part for part in parts if part)
    grams = cjk_bigrams(raw)
    return " ".join([raw] + grams)


def document(
    agent_id: str, name: str, description: str, card: Dict[str, Any]
) -> Tuple[str, str, str, str]:
    dotted = (agent_id or "").replace(".", " ").replace("_", " ").replace("-", " ")
    skills = " ".join(part for part in (dotted, _skill_blob(card)) if part)
    desc = description or ""
    desc_doc = " ".join([desc] + cjk_bigrams(desc) + cjk_bigrams(name or ""))
    return (agent_id, name or "", desc_doc, skills)


def upsert(
    conn: sqlite3.Connection,
    agent_id: str,
    name: str,
    description: str,
    card: Dict[str, Any],
) -> None:
    if not ensure_schema(conn):
        return
    conn.execute("DELETE FROM agent_fts WHERE agent_id = ?", (agent_id,))
    conn.execute(
        "INSERT INTO agent_fts(agent_id, name, description, skills) VALUES (?, ?, ?, ?)",
        document(agent_id, name, description, card),
    )


def delete(conn: sqlite3.Connection, agent_id: str) -> None:
    if not available(conn):
        return
    conn.execute("DELETE FROM agent_fts WHERE agent_id = ?", (agent_id,))


def rebuild_all(conn: sqlite3.Connection) -> int:
    if not ensure_schema(conn):
        return 0
    conn.execute("DELETE FROM agent_fts")
    rows = conn.execute("SELECT agent_id, name, description, card_json FROM agents").fetchall()
    n = 0
    for row in rows:
        card = json.loads(row["card_json"] or "{}")
        upsert(conn, row["agent_id"], row["name"], row["description"], card)
        n += 1
    return n


def migrate(conn: sqlite3.Connection) -> None:
    if not ensure_schema(conn):
        return
    agents = int(conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0])
    indexed = int(conn.execute("SELECT COUNT(*) FROM agent_fts").fetchone()[0])
    if agents != indexed:
        rebuild_all(conn)


def match_expr(q: str) -> Optional[str]:
    text = (q or "").strip()
    if not text:
        return None
    cleaned = _SPECIAL.sub(" ", text)
    tokens = [token for token in _WS.split(cleaned) if token]
    if not tokens:
        return None
    quoted = []
    for token in tokens:
        safe = token.replace('"', '""')
        if _is_cjk(token) and len(token) >= 2:
            grams = [token[i : i + 2] for i in range(len(token) - 1)]
            inner = " AND ".join('"{0}"'.format(g.replace('"', '""')) for g in grams)
            quoted.append("({0})".format(inner))
        else:
            quoted.append('"{0}"'.format(safe))
    return " OR ".join(quoted)


def match_ids(conn: sqlite3.Connection, q: str) -> Optional[List[str]]:
    expr = match_expr(q)
    if expr is None or not available(conn):
        return None
    try:
        rows = conn.execute(
            "SELECT agent_id FROM agent_fts WHERE agent_fts MATCH ?",
            (expr,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    seen = []  # type: List[str]
    for row in rows:
        agent_id = row[0] if not isinstance(row, sqlite3.Row) else row["agent_id"]
        if agent_id not in seen:
            seen.append(agent_id)
    return seen


def sql_in(ids: Sequence[str], column: str = "agent_id") -> Tuple[str, List[str]]:
    if not ids:
        return "1=0", []
    placeholders = ",".join("?" * len(ids))
    return "{0} IN ({1})".format(column, placeholders), list(ids)
