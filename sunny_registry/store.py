"""Persistence and query helpers."""

from __future__ import annotations

import json
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import security
from .card_validate import extract_agent_id, validate_card
from .config import Settings

ISO = "%Y-%m-%dT%H:%M:%SZ"


def secrets_token() -> str:
    return secrets.token_hex(8)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime(ISO)


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, ISO).replace(tzinfo=timezone.utc)


class StoreError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class Store:
    def __init__(self, conn: sqlite3.Connection, settings: Settings) -> None:
        self.conn = conn
        self.settings = settings

    def count_agents(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM agents").fetchone()
        return int(row["n"])

    def count_users(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"])

    def _public_user(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "user_id": row["user_id"],
            "username": row["username"],
            "role": row["role"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return self._public_user(row) if row else None

    def get_user_row(self, user_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return self._public_user(row) if row else None

    def get_user_row_by_username(self, username: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    def list_users(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM users ORDER BY role, username").fetchall()
        return [self._public_user(row) for row in rows]

    def count_admins(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'").fetchone()
        return int(row["n"])

    def create_user(self, username: str, password: str, role: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        username = security.validate_username(username)
        security.validate_password(password)
        role = security.validate_role(role)
        if self.get_user_by_username(username):
            raise StoreError(409, "username already exists")
        now = utcnow()
        uid = user_id or ("usr_" + secrets_token())
        self.conn.execute(
            """
            INSERT INTO users(user_id, username, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uid, username, security.hash_password(password), role, now, now),
        )
        self.conn.commit()
        user = self.get_user(uid)
        if not user:
            raise StoreError(500, "failed to create user")
        return user

    def delete_user(self, user_id: str) -> Dict[str, Any]:
        row = self.get_user_row(user_id)
        if not row:
            raise StoreError(404, "user not found")
        if row["role"] == "admin" and self.count_admins() <= 1:
            raise StoreError(409, "cannot delete the last admin")
        self.conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self.conn.commit()
        return {"ok": True, "user_id": user_id, "deleted": True}

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        row = self.get_user_row_by_username((username or "").strip())
        if not row or not security.verify_password(password, row["password_hash"]):
            return None
        return self._public_user(row)

    def owner_username(self, user_id: Optional[str]) -> Optional[str]:
        if not user_id:
            return None
        user = self.get_user(user_id)
        return user["username"] if user else None

    def find_agent_by_key(self, raw_key: str) -> Optional[str]:
        digest = security.hash_agent_key(raw_key, self.settings.ticket_secret)
        row = self.conn.execute(
            "SELECT agent_id FROM agents WHERE agent_key_hash = ?",
            (digest,),
        ).fetchone()
        return row["agent_id"] if row else None

    def runtime_status(self, row: sqlite3.Row) -> str:
        if row["lifecycle"] == "disabled":
            return "disabled"
        last = parse_iso(row["last_heartbeat_at"])
        if last is None:
            return "unknown"
        age = datetime.now(timezone.utc) - last
        if age > timedelta(seconds=self.settings.heartbeat_stale_s):
            return "stale"
        return "online"

    def _skills_from_card(self, card: dict) -> List[Dict[str, Any]]:
        items = []
        for skill in card.get("skills") or []:
            ext = skill.get("x-sunny") or {}
            items.append(
                {
                    "id": skill.get("id"),
                    "name": skill.get("name"),
                    "tags": skill.get("tags") or [],
                    "side_effects": ext.get("side_effects") or "read",
                    "data_class": ext.get("data_class") or "internal",
                }
            )
        return items

    def _replace_skills(self, agent_id: str, card: dict) -> None:
        self.conn.execute("DELETE FROM agent_skills WHERE agent_id = ?", (agent_id,))
        for skill in self._skills_from_card(card):
            self.conn.execute(
                """
                INSERT INTO agent_skills(agent_id, skill_id, name, tags_csv, side_effects, data_class)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    skill["id"],
                    skill["name"],
                    ",".join(skill["tags"]),
                    skill["side_effects"],
                    skill["data_class"],
                ),
            )

    def _next_rev(self, agent_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(rev), 0) AS n FROM revisions WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        return int(row["n"]) + 1

    def _add_revision(
        self,
        agent_id: str,
        action: str,
        actor: str,
        enrollment_source: Optional[str],
        card: Optional[dict],
        summary: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO revisions(agent_id, rev, action, actor, enrollment_source, card_json, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                self._next_rev(agent_id),
                action,
                actor,
                enrollment_source,
                json.dumps(card, ensure_ascii=False) if card is not None else None,
                summary,
                utcnow(),
            ),
        )

    def _prepare_card(self, card: dict, lifecycle: str) -> dict:
        errors = validate_card(card)
        if errors:
            raise StoreError(400, "card rejected: " + "; ".join(errors[:8]))
        prepared = json.loads(json.dumps(card))
        sunny = prepared.setdefault("x-sunny", {})
        sunny["lifecycle"] = lifecycle
        sunny["invoke_identity"] = "agent_service"
        sunny["scratch_access"] = "none"
        return prepared

    def _row_to_summary(self, row: sqlite3.Row) -> Dict[str, Any]:
        card = json.loads(row["card_json"])
        skills = self._skills_from_card(card)
        return {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "description": row["description"],
            "version": row["version"],
            "workspace": row["workspace"],
            "enrollment_source": row["enrollment_source"],
            "lifecycle": row["lifecycle"],
            "runtime_status": self.runtime_status(row),
            "access_tier": (card.get("x-sunny") or {}).get("access_tier"),
            "skill_count": len(skills),
            "skills": [{"id": s["id"], "name": s["name"], "tags": s["tags"]} for s in skills],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "created_by": row["created_by"] if "created_by" in row.keys() else None,
            "owner_username": self.owner_username(row["created_by"] if "created_by" in row.keys() else None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_row(self, agent_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()

    def register(
        self,
        card: dict,
        enrollment_source: str,
        actor: str,
        lifecycle: str = "registered",
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        if enrollment_source not in {"self", "hub"}:
            raise StoreError(400, "enrollment_source must be self or hub")
        prepared = self._prepare_card(card, lifecycle)
        agent_id = extract_agent_id(prepared)
        if self.get_row(agent_id):
            raise StoreError(409, "agent already registered: {0}".format(agent_id))
        raw_key = security.new_agent_key()
        now = utcnow()
        self.conn.execute(
            """
            INSERT INTO agents(
                agent_id, workspace, name, description, version, card_json,
                enrollment_source, lifecycle, last_heartbeat_at, agent_key_hash,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                agent_id,
                prepared["x-sunny"]["workspace"],
                prepared["name"],
                prepared["description"],
                prepared["version"],
                json.dumps(prepared, ensure_ascii=False),
                enrollment_source,
                lifecycle,
                security.hash_agent_key(raw_key, self.settings.ticket_secret),
                created_by,
                now,
                now,
            ),
        )
        self._replace_skills(agent_id, prepared)
        self._add_revision(
            agent_id,
            "create",
            actor,
            enrollment_source,
            prepared,
            "registered via {0}".format("agent push" if enrollment_source == "self" else "hub form"),
        )
        self.conn.commit()
        row = self.get_row(agent_id)
        result = self._row_to_summary(row)
        result["agent_key"] = raw_key
        result["card"] = prepared
        return result

    def update_card(self, agent_id: str, card: dict, actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if row["lifecycle"] == "disabled":
            raise StoreError(409, "enable the agent before updating the card")
        incoming_id = extract_agent_id(card) if isinstance(card, dict) else ""
        if incoming_id and incoming_id != agent_id:
            raise StoreError(400, "x-sunny.agent_id cannot change")
        prepared = self._prepare_card(card, row["lifecycle"])
        prepared["x-sunny"]["agent_id"] = agent_id
        now = utcnow()
        self.conn.execute(
            """
            UPDATE agents SET workspace=?, name=?, description=?, version=?, card_json=?, updated_at=?
            WHERE agent_id=?
            """,
            (
                prepared["x-sunny"]["workspace"],
                prepared["name"],
                prepared["description"],
                prepared["version"],
                json.dumps(prepared, ensure_ascii=False),
                now,
                agent_id,
            ),
        )
        self._replace_skills(agent_id, prepared)
        self._add_revision(agent_id, "update", actor, row["enrollment_source"], prepared, "card updated")
        self.conn.commit()
        return self.get_detail(agent_id)

    def patch_card(self, agent_id: str, patch: Dict[str, Any], actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        card = json.loads(row["card_json"])
        if patch.get("name") is not None:
            card["name"] = patch["name"]
        if patch.get("description") is not None:
            card["description"] = patch["description"]
        if patch.get("version") is not None:
            card["version"] = patch["version"]
        skills = list(card.get("skills") or [])
        if patch.get("skills") is not None:
            skills = list(patch["skills"])
        else:
            remove_ids = set(patch.get("remove_skill_ids") or [])
            if remove_ids:
                skills = [item for item in skills if item.get("id") not in remove_ids]
            for skill in patch.get("update_skills") or []:
                if not isinstance(skill, dict) or not skill.get("id"):
                    raise StoreError(400, "update_skills items need an id")
                replaced = False
                for index, existing in enumerate(skills):
                    if existing.get("id") == skill["id"]:
                        merged = json.loads(json.dumps(existing))
                        merged.update(skill)
                        if isinstance(existing.get("x-sunny"), dict) or isinstance(skill.get("x-sunny"), dict):
                            ext = dict(existing.get("x-sunny") or {})
                            ext.update(skill.get("x-sunny") or {})
                            merged["x-sunny"] = ext
                        skills[index] = merged
                        replaced = True
                        break
                if not replaced:
                    raise StoreError(404, "skill not found: {0}".format(skill["id"]))
            existing_ids = {item.get("id") for item in skills}
            for skill in patch.get("add_skills") or []:
                if not isinstance(skill, dict) or not skill.get("id"):
                    raise StoreError(400, "add_skills items need an id")
                if skill["id"] in existing_ids:
                    raise StoreError(409, "skill already exists: {0}".format(skill["id"]))
                skills.append(skill)
                existing_ids.add(skill["id"])
        card["skills"] = skills
        return self.update_card(agent_id, card, actor)

    def delete_agent(self, agent_id: str, actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        summary = self._row_to_summary(row)
        self._add_revision(agent_id, "delete", actor, row["enrollment_source"], None, "agent deleted")
        self.conn.execute("DELETE FROM agent_skills WHERE agent_id = ?", (agent_id,))
        self.conn.execute("DELETE FROM tickets WHERE caller_id = ? OR callee_id = ?", (agent_id, agent_id))
        self.conn.execute("DELETE FROM invocations WHERE caller_id = ? OR callee_id = ?", (agent_id, agent_id))
        self.conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        self.conn.commit()
        return {"ok": True, "deleted": True, "agent_id": agent_id, "name": summary["name"]}

    def set_lifecycle(self, agent_id: str, lifecycle: str, actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if lifecycle not in {"registered", "disabled"}:
            raise StoreError(400, "lifecycle must be registered or disabled")
        card = json.loads(row["card_json"])
        card["x-sunny"]["lifecycle"] = lifecycle
        now = utcnow()
        self.conn.execute(
            "UPDATE agents SET lifecycle=?, card_json=?, updated_at=? WHERE agent_id=?",
            (lifecycle, json.dumps(card, ensure_ascii=False), now, agent_id),
        )
        action = "disable" if lifecycle == "disabled" else "enable"
        self._add_revision(agent_id, action, actor, row["enrollment_source"], card, action)
        self.conn.commit()
        return self.get_detail(agent_id)

    def heartbeat(self, agent_id: str, actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if row["lifecycle"] == "disabled":
            raise StoreError(409, "disabled agent cannot heartbeat")
        now = utcnow()
        self.conn.execute(
            "UPDATE agents SET last_heartbeat_at=?, updated_at=? WHERE agent_id=?",
            (now, now, agent_id),
        )
        self._add_revision(agent_id, "heartbeat", actor, row["enrollment_source"], None, "heartbeat")
        self.conn.commit()
        return self.get_detail(agent_id)

    def issue_agent_key(self, agent_id: str, actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        raw_key = security.new_agent_key()
        now = utcnow()
        self.conn.execute(
            "UPDATE agents SET agent_key_hash=?, updated_at=? WHERE agent_id=?",
            (security.hash_agent_key(raw_key, self.settings.ticket_secret), now, agent_id),
        )
        self._add_revision(agent_id, "issue_key", actor, row["enrollment_source"], None, "new agent key issued")
        self.conn.commit()
        result = self.get_detail(agent_id)
        result["agent_key"] = raw_key
        return result

    def get_detail(self, agent_id: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        summary = self._row_to_summary(row)
        summary["card"] = json.loads(row["card_json"])
        return summary

    def list_agents(
        self,
        include_disabled: bool = True,
        only_registered: bool = False,
        q: Optional[str] = None,
        workspace: Optional[str] = None,
        enrollment_source: Optional[str] = None,
        runtime_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM agents"
        clauses = []
        args: List[Any] = []
        if only_registered:
            clauses.append("lifecycle = 'registered'")
        elif not include_disabled:
            clauses.append("lifecycle != 'disabled'")
        if workspace:
            clauses.append("workspace = ?")
            args.append(workspace)
        if enrollment_source:
            clauses.append("enrollment_source = ?")
            args.append(enrollment_source)
        if q:
            like = "%{0}%".format(q)
            clauses.append("(agent_id LIKE ? OR name LIKE ? OR description LIKE ?)")
            args.extend([like, like, like])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        items = []
        for row in self.conn.execute(sql, args):
            summary = self._row_to_summary(row)
            if runtime_status and summary["runtime_status"] != runtime_status:
                continue
            items.append(summary)
        return items

    def search(
        self,
        skill_id: Optional[str] = None,
        tag: Optional[str] = None,
        workspace: Optional[str] = None,
        q: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = """
            SELECT DISTINCT a.* FROM agents a
            JOIN agent_skills s ON s.agent_id = a.agent_id
            WHERE a.lifecycle = 'registered'
              AND s.side_effects = 'read'
        """
        args: List[Any] = []
        if skill_id:
            sql += " AND s.skill_id = ?"
            args.append(skill_id)
        if tag:
            sql += " AND (',' || s.tags_csv || ',') LIKE ?"
            args.append("%,{0},%".format(tag))
        if workspace:
            sql += " AND a.workspace = ?"
            args.append(workspace)
        if q:
            like = "%{0}%".format(q)
            sql += " AND (a.agent_id LIKE ? OR a.name LIKE ? OR s.skill_id LIKE ? OR s.name LIKE ?)"
            args.extend([like, like, like, like])
        sql += " ORDER BY a.name"
        return [self._row_to_summary(row) for row in self.conn.execute(sql, args)]

    def revisions(self, agent_id: str) -> List[Dict[str, Any]]:
        if not self.get_row(agent_id):
            raise StoreError(404, "agent not found")
        rows = self.conn.execute(
            """
            SELECT id, agent_id, rev, action, actor, enrollment_source, summary, created_at,
                   CASE WHEN card_json IS NULL THEN 0 ELSE 1 END AS has_card
            FROM revisions WHERE agent_id = ? ORDER BY rev DESC
            """,
            (agent_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def revision_card(self, agent_id: str, rev: int) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT card_json, rev, action, created_at FROM revisions WHERE agent_id=? AND rev=?",
            (agent_id, rev),
        ).fetchone()
        if not row or not row["card_json"]:
            raise StoreError(404, "revision snapshot not found")
        return {
            "agent_id": agent_id,
            "rev": row["rev"],
            "action": row["action"],
            "created_at": row["created_at"],
            "card": json.loads(row["card_json"]),
        }

    def activity(self, limit: int = 80) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT agent_id, rev, action, actor, enrollment_source, summary, created_at
            FROM revisions ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_ticket(self, payload: dict) -> None:
        issued = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc).strftime(ISO)
        expires = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc).strftime(ISO)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tickets(jti, caller_id, callee_id, skill_id, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payload["jti"], payload["caller"], payload["callee"], payload["skill"], issued, expires),
        )
        self.conn.commit()

    def record_invocation(
        self,
        caller_id: str,
        callee_id: str,
        skill_id: str,
        status: str,
        trace_id: Optional[str],
        ticket_jti: Optional[str],
        actor: str,
    ) -> Dict[str, Any]:
        if status not in {"ok", "denied", "error"}:
            raise StoreError(400, "status must be ok, denied, or error")
        if not self.get_row(caller_id) or not self.get_row(callee_id):
            raise StoreError(404, "caller or callee not found")
        now = utcnow()
        cur = self.conn.execute(
            """
            INSERT INTO invocations(caller_id, callee_id, skill_id, status, trace_id, ticket_jti, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (caller_id, callee_id, skill_id, status, trace_id, ticket_jti, now),
        )
        self._add_revision(
            callee_id,
            "invoke",
            actor,
            None,
            None,
            "{0} -> {1} #{2} {3}".format(caller_id, callee_id, skill_id, status),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "caller_id": caller_id,
            "callee_id": callee_id,
            "skill_id": skill_id,
            "status": status,
            "trace_id": trace_id,
            "created_at": now,
        }

    def graph(self) -> Dict[str, Any]:
        nodes = self.list_agents(include_disabled=True, only_registered=False)
        edges = {}
        for row in self.conn.execute(
            "SELECT caller_id, callee_id, skill_id, issued_at FROM tickets"
        ):
            key = (row["caller_id"], row["callee_id"], row["skill_id"])
            item = edges.setdefault(
                key,
                {
                    "caller_id": row["caller_id"],
                    "callee_id": row["callee_id"],
                    "skill_id": row["skill_id"],
                    "ticket_count": 0,
                    "invoke_count": 0,
                    "last_at": row["issued_at"],
                },
            )
            item["ticket_count"] += 1
            if row["issued_at"] > item["last_at"]:
                item["last_at"] = row["issued_at"]
        for row in self.conn.execute(
            "SELECT caller_id, callee_id, skill_id, created_at FROM invocations"
        ):
            key = (row["caller_id"], row["callee_id"], row["skill_id"])
            item = edges.setdefault(
                key,
                {
                    "caller_id": row["caller_id"],
                    "callee_id": row["callee_id"],
                    "skill_id": row["skill_id"],
                    "ticket_count": 0,
                    "invoke_count": 0,
                    "last_at": row["created_at"],
                },
            )
            item["invoke_count"] += 1
            if row["created_at"] > item["last_at"]:
                item["last_at"] = row["created_at"]
        return {"nodes": nodes, "edges": list(edges.values())}

    def skill_on_agent(self, agent_id: str, skill_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM agent_skills WHERE agent_id=? AND skill_id=?",
            (agent_id, skill_id),
        ).fetchone()
        return dict(row) if row else None
