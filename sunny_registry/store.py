"""Persistence and query helpers."""

from __future__ import annotations

import json
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import fts, observe, policy, probe, pull, security
from .a2a_export import mark_extended_card
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
        self.last_sweep: Optional[Dict[str, Any]] = None
        self.sweep_timer = None

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

    def _is_fresh(self, value: Optional[str], window_s: Optional[float] = None) -> bool:
        parsed = parse_iso(value)
        if parsed is None:
            return False
        limit = self.settings.heartbeat_stale_s if window_s is None else window_s
        return datetime.now(timezone.utc) - parsed <= timedelta(seconds=limit)

    def runtime_status(self, row: sqlite3.Row) -> str:
        if row["lifecycle"] == "disabled":
            return "disabled"
        if self._is_fresh(row["last_heartbeat_at"]):
            return "online"
        probe_at = row["probe_checked_at"] if "probe_checked_at" in row.keys() else None
        probe_ok = row["probe_ok"] if "probe_ok" in row.keys() else None
        if self._is_fresh(probe_at):
            return "online" if probe_ok else "unreachable"
        if parse_iso(row["last_heartbeat_at"]) is None:
            return "unknown"
        return "stale"

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
        return mark_extended_card(prepared)

    def _row_to_summary(self, row: sqlite3.Row) -> Dict[str, Any]:
        card = json.loads(row["card_json"])
        skills = self._skills_from_card(card)
        stored_discovery = row["discovery"] if "discovery" in row.keys() else None
        return {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "description": row["description"],
            "version": row["version"],
            "workspace": row["workspace"],
            "enrollment_source": row["enrollment_source"],
            "lifecycle": row["lifecycle"],
            "discovery": policy.discovery_of(card, stored_discovery),
            "approval_status": policy.approval_status_of(
                row["approval_status"] if "approval_status" in row.keys() else None,
                stored_discovery,
            ),
            "approval_reason": row["approval_reason"] if "approval_reason" in row.keys() else None,
            "approval_decided_at": row["approval_decided_at"] if "approval_decided_at" in row.keys() else None,
            "approval_decided_by": row["approval_decided_by"] if "approval_decided_by" in row.keys() else None,
            "runtime_status": self.runtime_status(row),
            "access_tier": (card.get("x-sunny") or {}).get("access_tier"),
            "skill_count": len(skills),
            "skills": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "tags": s["tags"],
                    "data_class": s["data_class"],
                }
                for s in skills
            ],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "probe": self._probe_from_row(row),
            "card_source_url": row["card_source_url"] if "card_source_url" in row.keys() else None,
            "created_by": row["created_by"] if "created_by" in row.keys() else None,
            "owner_username": self.owner_username(row["created_by"] if "created_by" in row.keys() else None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _probe_from_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        keys = row.keys()
        if "probe_checked_at" not in keys or row["probe_checked_at"] is None:
            return {
                "ok": None,
                "url": None,
                "status_code": None,
                "error": None,
                "category": None,
                "checked_at": None,
            }
        ok_raw = row["probe_ok"] if "probe_ok" in keys else None
        return {
            "ok": None if ok_raw is None else bool(ok_raw),
            "url": row["probe_url"] if "probe_url" in keys else None,
            "status_code": row["probe_status_code"] if "probe_status_code" in keys else None,
            "error": row["probe_error"] if "probe_error" in keys else None,
            "category": row["probe_category"] if "probe_category" in keys else None,
            "checked_at": row["probe_checked_at"],
        }

    def get_row(self, agent_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()

    def _refresh_fts(self, agent_id: str) -> None:
        row = self.get_row(agent_id)
        if not row:
            fts.delete(self.conn, agent_id)
            return
        fts.upsert(
            self.conn,
            agent_id,
            row["name"],
            row["description"],
            json.loads(row["card_json"] or "{}"),
        )

    def _q_clause(self, q: Optional[str], like_sql: str, like_n: int, id_column: str) -> Tuple[Optional[str], List[Any]]:
        text = (q or "").strip()
        if not text:
            return None, []
        ids = fts.match_ids(self.conn, text)
        if ids is not None:
            clause, args = fts.sql_in(ids, id_column)
            return clause, args
        like = "%{0}%".format(text)
        return like_sql, [like] * like_n

    def register(
        self,
        card: dict,
        enrollment_source: str,
        actor: str,
        lifecycle: str = "registered",
        created_by: Optional[str] = None,
        source_url: Optional[str] = None,
        summary: Optional[str] = None,
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
                created_by, discovery, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
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
                policy.discovery_of(prepared),
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
            summary
            or "registered via {0}".format("agent push" if enrollment_source == "self" else "hub form"),
        )
        if source_url:
            self._set_card_source_url(agent_id, source_url)
        self._write_approval(
            agent_id,
            policy.initial_approval_status(policy.discovery_of(prepared)),
        )
        self._refresh_fts(agent_id)
        self.conn.commit()
        row = self.get_row(agent_id)
        result = self._row_to_summary(row)
        result["agent_key"] = raw_key
        result["card"] = prepared
        return result

    def _write_approval(
        self,
        agent_id: str,
        status: str,
        reason: Optional[str] = None,
        decided_by: Optional[str] = None,
        decided_at: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE agents
            SET approval_status=?, approval_reason=?, approval_decided_at=?, approval_decided_by=?
            WHERE agent_id=?
            """,
            (status, reason, decided_at, decided_by, agent_id),
        )

    def _set_card_source_url(self, agent_id: str, url: Optional[str]) -> None:
        self.conn.execute(
            "UPDATE agents SET card_source_url=? WHERE agent_id=?",
            (url, agent_id),
        )

    def _http_transport(self, transport=None):
        if transport is not None:
            return transport
        return getattr(self.settings, "http_transport", None)

    def fetch_card_from_url(self, url: str, transport=None) -> Dict[str, Any]:
        try:
            return pull.fetch_sunny_card(
                url,
                self.settings.pull_timeout_s,
                self._http_transport(transport),
            )
        except pull.PullError as exc:
            raise StoreError(exc.status_code, exc.detail)

    def apply_pulled_update(
        self,
        agent_id: str,
        card: dict,
        source_url: str,
        actor: str,
        allow_promote: bool = False,
    ) -> Dict[str, Any]:
        self.update_card(
            agent_id,
            card,
            actor,
            summary="card pulled from well-known",
            allow_promote=allow_promote,
        )
        self._set_card_source_url(agent_id, source_url)
        self.conn.commit()
        self.record_event(
            "card",
            actor,
            callee_id=agent_id,
            summary="pull refresh {0}".format(agent_id),
            detail={"source_url": source_url},
        )
        return self.get_detail(agent_id)

    def refresh_from_source(self, agent_id: str, actor: str, transport=None) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if row["lifecycle"] == "disabled":
            raise StoreError(409, "enable the agent before refreshing the card")
        source = row["card_source_url"] if "card_source_url" in row.keys() else None
        if not source:
            raise StoreError(400, "agent has no card_source_url; pull by url first")
        try:
            fetched = pull.fetch_sunny_card(
                source,
                self.settings.pull_timeout_s,
                self._http_transport(transport),
            )
        except pull.PullError as exc:
            self.record_event(
                "card",
                actor,
                status="error",
                callee_id=agent_id,
                summary="refresh failed: {0}".format(exc.detail),
                detail={"url": source, "error": exc.detail},
            )
            raise StoreError(exc.status_code, exc.detail)
        incoming_id = extract_agent_id(fetched["card"])
        if incoming_id and incoming_id != agent_id:
            self.record_event(
                "card",
                actor,
                status="error",
                callee_id=agent_id,
                summary="refresh rejected: agent_id changed",
                detail={"url": source, "incoming_id": incoming_id},
            )
            raise StoreError(400, "x-sunny.agent_id cannot change")
        try:
            self.update_card(
                agent_id,
                fetched["card"],
                actor,
                summary="card refreshed from well-known",
                allow_promote=False,
            )
        except StoreError:
            self.record_event(
                "card",
                actor,
                status="error",
                callee_id=agent_id,
                summary="refresh rejected: card invalid",
                detail={"url": fetched.get("source_url") or source},
            )
            raise
        self._set_card_source_url(agent_id, fetched["source_url"])
        self._touch_card_refreshed_at(agent_id)
        self.conn.commit()
        self.record_event(
            "card",
            actor,
            callee_id=agent_id,
            summary="refresh {0}".format(agent_id),
            detail={"source_url": fetched["source_url"]},
        )
        return self.get_detail(agent_id)

    def _touch_card_refreshed_at(self, agent_id: str) -> None:
        now = utcnow()
        self.conn.execute(
            "UPDATE agents SET card_refreshed_at=?, updated_at=? WHERE agent_id=?",
            (now, now, agent_id),
        )
        self.conn.commit()

    def sweep_once(self, actor: str = "system:sweep", transport=None) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT agent_id FROM agents WHERE lifecycle = 'registered' ORDER BY agent_id"
        ).fetchall()
        probed = 0
        refreshed = 0
        errors = 0
        for row in rows:
            agent_id = row["agent_id"]
            try:
                self.probe_agent(agent_id, actor, transport=transport)
                probed += 1
            except StoreError:
                errors += 1
                continue
            current = self.get_row(agent_id)
            if not current:
                continue
            source = current["card_source_url"] if "card_source_url" in current.keys() else None
            if not source:
                continue
            last_refresh = (
                current["card_refreshed_at"] if "card_refreshed_at" in current.keys() else None
            )
            if self._is_fresh(last_refresh, self.settings.refresh_interval_s):
                continue
            try:
                self.refresh_from_source(agent_id, actor, transport=transport)
                refreshed += 1
            except StoreError:
                errors += 1
                self._touch_card_refreshed_at(agent_id)
        summary = {
            "probed": probed,
            "refreshed": refreshed,
            "errors": errors,
            "at": utcnow(),
        }
        self.last_sweep = summary
        return summary

    def update_card(
        self,
        agent_id: str,
        card: dict,
        actor: str,
        summary: str = "card updated",
        allow_promote: bool = False,
    ) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if row["lifecycle"] == "disabled":
            raise StoreError(409, "enable the agent before updating the card")
        incoming_id = extract_agent_id(card) if isinstance(card, dict) else ""
        if incoming_id and incoming_id != agent_id:
            raise StoreError(400, "x-sunny.agent_id cannot change")
        old_discovery = policy.discovery_of(
            json.loads(row["card_json"]),
            row["discovery"] if "discovery" in row.keys() else None,
        )
        old_status = row["approval_status"] if "approval_status" in row.keys() else None
        old_version = row["version"]
        prepared = self._prepare_card(card, row["lifecycle"])
        prepared["x-sunny"]["agent_id"] = agent_id
        new_discovery = policy.discovery_of(prepared)
        if (
            not allow_promote
            and old_discovery == "approval_required"
            and new_discovery == "registered_peers"
        ):
            raise StoreError(403, "cannot self-approve; an admin must approve this card")
        now = utcnow()
        self.conn.execute(
            """
            UPDATE agents SET workspace=?, name=?, description=?, version=?, card_json=?, discovery=?, updated_at=?
            WHERE agent_id=?
            """,
            (
                prepared["x-sunny"]["workspace"],
                prepared["name"],
                prepared["description"],
                prepared["version"],
                json.dumps(prepared, ensure_ascii=False),
                new_discovery,
                now,
                agent_id,
            ),
        )
        next_status = policy.next_approval_status(old_discovery, old_status, new_discovery, allow_promote)
        if next_status == policy.APPROVAL_PENDING:
            self._write_approval(agent_id, next_status)
        elif next_status == policy.APPROVAL_APPROVED:
            self._write_approval(agent_id, next_status, decided_by=actor, decided_at=now)
        else:
            self._write_approval(agent_id, next_status)
        self._replace_skills(agent_id, prepared)
        self._add_revision(agent_id, "update", actor, row["enrollment_source"], prepared, summary)
        self._refresh_fts(agent_id)
        if (prepared.get("version") or "") != (old_version or ""):
            self._record_card_change(agent_id, old_version or "", prepared.get("version") or "", actor)
        self.conn.commit()
        return self.get_detail(agent_id)

    def approve_agent(self, agent_id: str, actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if row["lifecycle"] == "disabled":
            raise StoreError(409, "enable the agent before approving")
        card = json.loads(row["card_json"])
        discovery = policy.discovery_of(card, row["discovery"] if "discovery" in row.keys() else None)
        status = policy.approval_status_of(
            row["approval_status"] if "approval_status" in row.keys() else None,
            discovery,
        )
        if not policy.is_awaiting_approval(discovery, status):
            raise StoreError(409, "agent is not awaiting approval")
        card.setdefault("x-sunny", {})["discovery"] = policy.PEER_VISIBLE_DISCOVERY
        now = utcnow()
        self.conn.execute(
            """
            UPDATE agents SET card_json=?, discovery=?, updated_at=? WHERE agent_id=?
            """,
            (json.dumps(card, ensure_ascii=False), policy.PEER_VISIBLE_DISCOVERY, now, agent_id),
        )
        self._write_approval(agent_id, policy.APPROVAL_APPROVED, decided_by=actor, decided_at=now)
        self._add_revision(agent_id, "approve", actor, row["enrollment_source"], card, "card approved")
        self.conn.commit()
        self.record_event(
            "card",
            actor,
            callee_id=agent_id,
            summary="approve {0}".format(agent_id),
            detail={"discovery": policy.PEER_VISIBLE_DISCOVERY},
        )
        return self.get_detail(agent_id)

    def reject_agent(self, agent_id: str, actor: str, reason: str) -> Dict[str, Any]:
        note = (reason or "").strip()
        if not note:
            raise StoreError(400, "reject reason is required")
        if len(note) > 500:
            raise StoreError(400, "reject reason is too long")
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if row["lifecycle"] == "disabled":
            raise StoreError(409, "enable the agent before rejecting")
        card = json.loads(row["card_json"])
        discovery = policy.discovery_of(card, row["discovery"] if "discovery" in row.keys() else None)
        status = policy.approval_status_of(
            row["approval_status"] if "approval_status" in row.keys() else None,
            discovery,
        )
        if status == policy.APPROVAL_APPROVED or discovery == policy.PEER_VISIBLE_DISCOVERY:
            raise StoreError(409, "approved agent is not awaiting rejection")
        if discovery != "approval_required" and status != policy.APPROVAL_PENDING:
            raise StoreError(409, "agent is not awaiting approval")
        card.setdefault("x-sunny", {})["discovery"] = "approval_required"
        now = utcnow()
        self.conn.execute(
            """
            UPDATE agents SET card_json=?, discovery=?, updated_at=? WHERE agent_id=?
            """,
            (json.dumps(card, ensure_ascii=False), "approval_required", now, agent_id),
        )
        self._write_approval(
            agent_id,
            policy.APPROVAL_REJECTED,
            reason=note,
            decided_by=actor,
            decided_at=now,
        )
        self._add_revision(agent_id, "reject", actor, row["enrollment_source"], card, "card rejected")
        self.conn.commit()
        self.record_event(
            "card",
            actor,
            status="denied",
            callee_id=agent_id,
            summary="reject {0}".format(agent_id),
            detail={"reason": note},
        )
        return self.get_detail(agent_id)

    def list_approvals(self, status: str = policy.APPROVAL_PENDING) -> List[Dict[str, Any]]:
        if status not in {policy.APPROVAL_PENDING, policy.APPROVAL_REJECTED, policy.APPROVAL_APPROVED}:
            raise StoreError(400, "approval status must be pending, rejected, or approved")
        items = []
        for row in self.conn.execute("SELECT * FROM agents ORDER BY updated_at DESC"):
            summary = self._row_to_summary(row)
            if summary["approval_status"] == status:
                items.append(summary)
        return items

    def patch_card(
        self,
        agent_id: str,
        patch: Dict[str, Any],
        actor: str,
        allow_promote: bool = False,
    ) -> Dict[str, Any]:
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
        return self.update_card(agent_id, card, actor, allow_promote=allow_promote)

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
        fts.delete(self.conn, agent_id)
        self.conn.commit()
        return {"ok": True, "deleted": True, "agent_id": agent_id, "name": summary["name"]}

    def _record_card_change(self, agent_id: str, old_version: str, new_version: str, actor: str) -> None:
        self.conn.execute(
            """
            INSERT INTO card_changes(agent_id, old_version, new_version, actor, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, old_version, new_version, actor, utcnow()),
        )

    def list_card_changes(
        self,
        since_id: int = 0,
        agent_id: Optional[str] = None,
        peer_visible_only: bool = False,
        limit: int = 100,
    ) -> Dict[str, Any]:
        if since_id < 0:
            since_id = 0
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        sql = """
            SELECT c.id, c.agent_id, c.old_version, c.new_version, c.actor, c.created_at
            FROM card_changes c
            JOIN agents a ON a.agent_id = c.agent_id
            WHERE c.id > ?
        """
        args: List[Any] = [since_id]
        if agent_id:
            sql += " AND c.agent_id = ?"
            args.append(agent_id)
        if peer_visible_only:
            sql += (
                " AND a.lifecycle IN ('registered', 'deprecated')"
                " AND COALESCE(a.discovery, 'registered_peers') = 'registered_peers'"
            )
        sql += " ORDER BY c.id ASC LIMIT ?"
        args.append(limit)
        items = [dict(row) for row in self.conn.execute(sql, args)]
        next_since = items[-1]["id"] if items else since_id
        return {"items": items, "count": len(items), "since": since_id, "next_since": next_since}

    def set_lifecycle(self, agent_id: str, lifecycle: str, actor: str) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if lifecycle not in policy.KNOWN_LIFECYCLES:
            raise StoreError(400, "lifecycle must be registered, deprecated, or disabled")
        if lifecycle == policy.LIFECYCLE_DEPRECATED and row["lifecycle"] == policy.LIFECYCLE_DISABLED:
            raise StoreError(409, "enable the agent before deprecating")
        card = json.loads(row["card_json"])
        card["x-sunny"]["lifecycle"] = lifecycle
        now = utcnow()
        self.conn.execute(
            "UPDATE agents SET lifecycle=?, card_json=?, updated_at=? WHERE agent_id=?",
            (lifecycle, json.dumps(card, ensure_ascii=False), now, agent_id),
        )
        if lifecycle == policy.LIFECYCLE_DISABLED:
            action = "disable"
        elif lifecycle == policy.LIFECYCLE_DEPRECATED:
            action = "deprecate"
        else:
            action = "enable"
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

    def probe_agent(self, agent_id: str, actor: str, transport=None) -> Dict[str, Any]:
        row = self.get_row(agent_id)
        if not row:
            raise StoreError(404, "agent not found")
        if row["lifecycle"] == "disabled":
            raise StoreError(409, "disabled agent cannot be probed")
        card = json.loads(row["card_json"])
        result = probe.probe_card(
            card,
            self.settings.probe_timeout_s,
            transport=self._http_transport(transport),
        )
        now = utcnow()
        category = result.get("category") or probe.classify_probe(result)
        self.conn.execute(
            """
            UPDATE agents
            SET probe_ok=?, probe_status_code=?, probe_url=?, probe_error=?,
                probe_category=?, probe_checked_at=?, updated_at=?
            WHERE agent_id=?
            """,
            (
                1 if result["ok"] else 0,
                result.get("status_code"),
                result.get("url"),
                result.get("error"),
                category,
                now,
                now,
                agent_id,
            ),
        )
        self.conn.commit()
        self.record_event(
            "card",
            actor,
            status="ok" if result["ok"] else "error",
            callee_id=agent_id,
            summary="probe {0} {1}".format(agent_id, category if not result["ok"] else "ok"),
            detail={
                "ok": result["ok"],
                "url": result.get("url"),
                "status_code": result.get("status_code"),
                "error": result.get("error"),
                "category": category,
            },
        )
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
        discovery: Optional[str] = None,
        approval_status: Optional[str] = None,
        peer_visible_only: bool = False,
        include_owned_by: Optional[str] = None,
        include_agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM agents"
        clauses = []
        args: List[Any] = []
        if only_registered:
            clauses.append("lifecycle IN ('registered', 'deprecated')")
        elif not include_disabled:
            clauses.append("lifecycle != 'disabled'")
        if workspace:
            clauses.append("workspace = ?")
            args.append(workspace)
        if enrollment_source:
            clauses.append("enrollment_source = ?")
            args.append(enrollment_source)
        if discovery:
            clauses.append("COALESCE(discovery, 'registered_peers') = ?")
            args.append(discovery)
        if approval_status:
            clauses.append("COALESCE(approval_status, 'none') = ?")
            args.append(approval_status)
        if q:
            clause, q_args = self._q_clause(
                q,
                "(agent_id LIKE ? OR name LIKE ? OR description LIKE ?)",
                3,
                "agent_id",
            )
            if clause:
                clauses.append(clause)
                args.extend(q_args)
        if peer_visible_only:
            visible = ["COALESCE(discovery, 'registered_peers') = 'registered_peers'"]
            if include_owned_by:
                visible.append("created_by = ?")
                args.append(include_owned_by)
            if include_agent_id:
                visible.append("agent_id = ?")
                args.append(include_agent_id)
            clauses.append("(" + " OR ".join(visible) + ")")
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
        only_alive: bool = True,
    ) -> List[Dict[str, Any]]:
        sql = """
            SELECT DISTINCT a.* FROM agents a
            JOIN agent_skills s ON s.agent_id = a.agent_id
            WHERE a.lifecycle IN ('registered', 'deprecated')
              AND COALESCE(a.discovery, 'registered_peers') = 'registered_peers'
              AND s.side_effects = 'read'
              AND s.data_class IN ('public', 'internal')
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
            clause, q_args = self._q_clause(
                q,
                "(a.agent_id LIKE ? OR a.name LIKE ? OR a.description LIKE ? OR s.skill_id LIKE ? OR s.name LIKE ?)",
                5,
                "a.agent_id",
            )
            if clause:
                sql += " AND " + clause
                args.extend(q_args)
        sql += " ORDER BY a.name"
        items = []
        for row in self.conn.execute(sql, args):
            if only_alive and self.runtime_status(row) != "online":
                continue
            items.append(self._row_to_summary(row))
        return items

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

    def record_event(
        self,
        kind: str,
        actor: str,
        *,
        status: str = "ok",
        caller_id: Optional[str] = None,
        callee_id: Optional[str] = None,
        skill_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        ticket_jti: Optional[str] = None,
        summary: str = "",
        detail: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        if kind not in observe.KINDS:
            raise StoreError(400, "unknown observe kind")
        if status not in observe.EVENT_STATUSES:
            raise StoreError(400, "unknown observe status")
        now = utcnow()
        cur = self.conn.execute(
            """
            INSERT INTO observe_events(
                kind, status, actor, caller_id, callee_id, skill_id, trace_id,
                ticket_jti, summary, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                status,
                actor,
                caller_id,
                callee_id,
                skill_id,
                observe.clip(trace_id, 80),
                ticket_jti,
                observe.clip(summary, 240) or kind,
                json.dumps(detail or {}, ensure_ascii=False),
                now,
            ),
        )
        if commit:
            self.conn.commit()
        return observe.shape_event(
            event_id="obs:{0}".format(cur.lastrowid),
            kind=kind,
            status=status,
            actor=actor,
            created_at=now,
            caller_id=caller_id,
            callee_id=callee_id,
            skill_id=skill_id,
            trace_id=trace_id,
            ticket_jti=ticket_jti,
            summary=summary,
            detail=detail or {},
        )

    def activity(
        self,
        limit: int = 80,
        kind: Optional[str] = None,
        trace_id: Optional[str] = None,
        q: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if kind and kind not in observe.KINDS:
            raise StoreError(400, "kind must be search, ticket, invoke, or card")
        items: List[Dict[str, Any]] = []
        if kind != "card":
            sql = "SELECT * FROM observe_events"
            clauses = []
            args: List[Any] = []
            if kind:
                clauses.append("kind = ?")
                args.append(kind)
            if trace_id:
                clauses.append("trace_id = ?")
                args.append(trace_id)
            if q:
                like = "%{0}%".format(q)
                clauses.append(
                    "(actor LIKE ? OR caller_id LIKE ? OR callee_id LIKE ? OR skill_id LIKE ? OR summary LIKE ? OR ticket_jti LIKE ? OR trace_id LIKE ?)"
                )
                args.extend([like, like, like, like, like, like, like])
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY id DESC LIMIT ?"
            args.append(limit)
            for row in self.conn.execute(sql, args):
                detail = {}
                if row["detail_json"]:
                    try:
                        detail = json.loads(row["detail_json"])
                    except Exception:
                        detail = {}
                items.append(
                    observe.shape_event(
                        event_id="obs:{0}".format(row["id"]),
                        kind=row["kind"],
                        status=row["status"],
                        actor=row["actor"],
                        created_at=row["created_at"],
                        caller_id=row["caller_id"],
                        callee_id=row["callee_id"],
                        skill_id=row["skill_id"],
                        trace_id=row["trace_id"],
                        ticket_jti=row["ticket_jti"],
                        summary=row["summary"],
                        detail=detail,
                    )
                )
        if kind in {None, "card"} and not trace_id:
            rev_sql = """
                SELECT id, agent_id, rev, action, actor, enrollment_source, summary, created_at
                FROM revisions
            """
            rev_args: List[Any] = []
            if q:
                rev_sql += " WHERE agent_id LIKE ? OR actor LIKE ? OR summary LIKE ? OR action LIKE ?"
                like = "%{0}%".format(q)
                rev_args.extend([like, like, like, like])
            rev_sql += " ORDER BY id DESC LIMIT ?"
            rev_args.append(limit)
            for row in self.conn.execute(rev_sql, rev_args):
                items.append(
                    observe.shape_event(
                        event_id="rev:{0}".format(row["id"]),
                        kind="card",
                        status="ok",
                        actor=row["actor"],
                        created_at=row["created_at"],
                        callee_id=row["agent_id"],
                        agent_id=row["agent_id"],
                        action=row["action"],
                        summary=row["summary"],
                        detail={"rev": row["rev"], "enrollment_source": row["enrollment_source"]},
                    )
                )
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items[:limit]

    def record_ticket(self, payload: dict) -> None:
        issued = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc).strftime(ISO)
        expires = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc).strftime(ISO)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tickets(jti, caller_id, callee_id, skill_id, card_version, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["jti"],
                payload["caller"],
                payload["callee"],
                payload["skill"],
                payload.get("card_version") or "",
                issued,
                expires,
            ),
        )
        self.record_event(
            "ticket",
            "agent:{0}".format(payload["caller"]),
            status="issued",
            caller_id=payload["caller"],
            callee_id=payload["callee"],
            skill_id=payload["skill"],
            ticket_jti=payload["jti"],
            summary="{0} -> {1} #{2} issued".format(payload["caller"], payload["callee"], payload["skill"]),
            detail={"card_version": payload.get("card_version") or ""},
            commit=False,
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
        self.record_event(
            "invoke",
            actor,
            status=status if status in observe.EVENT_STATUSES else "ok",
            caller_id=caller_id,
            callee_id=callee_id,
            skill_id=skill_id,
            trace_id=trace_id,
            ticket_jti=ticket_jti,
            summary="{0} -> {1} #{2} {3}".format(caller_id, callee_id, skill_id, status),
            commit=False,
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
