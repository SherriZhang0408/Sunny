"""Admin / developer / enroll / agent-key auth and short-lived call tickets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,31}$")
PBKDF2_ROUNDS = 80000
ADMIN_USER_ID = "usr_admin"
DEVELOPER_USER_ID = "usr_developer"


def _cmp(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def hash_agent_key(raw: str, secret: str) -> str:
    return hashlib.sha256("{0}:{1}".format(secret, raw).encode("utf-8")).hexdigest()


def new_agent_key() -> str:
    return "sak_" + secrets.token_urlsafe(24)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return "pbkdf2${0}${1}${2}".format(PBKDF2_ROUNDS, salt, digest.hex())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    try:
        iterations = int(rounds)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return hmac.compare_digest(digest.hex(), digest_hex)


def validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.match(value):
        raise HTTPException(status_code=400, detail="username must be 2-32 chars, start with a letter")
    return value


def validate_password(password: str) -> str:
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="password must be at least 6 characters")
    return password


def validate_role(role: str) -> str:
    value = (role or "").strip()
    if value not in {"admin", "developer"}:
        raise HTTPException(status_code=400, detail="role must be admin or developer")
    return value


def _sign_payload(secret: str, payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return "{0}.{1}".format(
        base64.urlsafe_b64encode(body).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(sig).decode("ascii").rstrip("="),
    )


def _b64decode(part: str) -> bytes:
    pad = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + pad)


def _unsign_payload(secret: str, token: str) -> Dict[str, Any]:
    try:
        left, right = token.split(".", 1)
        body = _b64decode(left)
        sig = _b64decode(right)
    except (ValueError, Exception):
        raise HTTPException(status_code=401, detail="malformed ticket")
    expect = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        raise HTTPException(status_code=401, detail="invalid ticket signature")
    return json.loads(body.decode("utf-8"))


def issue_ticket(
    secret: str,
    caller: str,
    callee: str,
    skill_id: str,
    ttl_s: int,
    card_version: Optional[str] = None,
) -> Dict[str, Any]:
    now = int(time.time())
    payload = {
        "iss": "sunny-registry",
        "caller": caller,
        "callee": callee,
        "skill": skill_id,
        "iat": now,
        "exp": now + ttl_s,
        "jti": secrets.token_hex(8),
    }
    if card_version:
        payload["card_version"] = card_version
    token = _sign_payload(secret, payload)
    return {"ticket": token, "expires_at": payload["exp"], "jti": payload["jti"], "payload": payload}


def verify_ticket(secret: str, token: str) -> Dict[str, Any]:
    payload = _unsign_payload(secret, token)
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="ticket expired")
    return payload


def issue_session(secret: str, user: Dict[str, Any], ttl_s: int) -> Dict[str, Any]:
    now = int(time.time())
    payload = {
        "iss": "sunny-registry",
        "typ": "session",
        "kind": user["role"],
        "user_id": user["user_id"],
        "username": user["username"],
        "iat": now,
        "exp": now + ttl_s,
        "jti": secrets.token_hex(8),
    }
    return {"token": _sign_payload(secret, payload), "expires_at": payload["exp"], "payload": payload}


def verify_session(secret: str, token: str) -> Optional[Dict[str, Any]]:
    if "." not in token:
        return None
    try:
        payload = _unsign_payload(secret, token)
    except HTTPException:
        return None
    if payload.get("typ") != "session":
        return None
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="session expired")
    return payload


class Principal:
    def __init__(
        self,
        kind: str,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> None:
        self.kind = kind  # admin | developer | agent | anonymous
        self.agent_id = agent_id
        self.user_id = user_id
        self.username = username

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"

    @property
    def is_developer(self) -> bool:
        return self.kind == "developer"

    @property
    def is_hub_user(self) -> bool:
        return self.kind in {"admin", "developer"}

    @property
    def is_agent(self) -> bool:
        return self.kind == "agent"

    @property
    def actor(self) -> str:
        if self.is_hub_user:
            return "{0}:{1}".format(self.kind, self.username or self.user_id or "unknown")
        if self.agent_id:
            return "agent:{0}".format(self.agent_id)
        return "anonymous"


def bearer_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    prefix = "bearer "
    if authorization.lower().startswith(prefix):
        return authorization[len(prefix) :].strip()
    return None


def _admin_from_store(store) -> Principal:
    user = None
    if hasattr(store, "get_user"):
        user = store.get_user(ADMIN_USER_ID) or store.get_user_by_username("admin")
    if user:
        return Principal("admin", user_id=user["user_id"], username=user["username"])
    return Principal("admin", username="admin")


def resolve_principal(
    settings,
    store,
    authorization: Optional[str],
    agent_key: Optional[str],
) -> Principal:
    token = bearer_from_header(authorization)
    if token and _cmp(token, settings.admin_token):
        return _admin_from_store(store)
    if token:
        session = verify_session(settings.ticket_secret, token)
        if session:
            return Principal(
                session.get("kind") or "developer",
                user_id=session.get("user_id"),
                username=session.get("username"),
            )
    raw_key = agent_key or token
    if raw_key:
        agent_id = store.find_agent_by_key(raw_key)
        if agent_id:
            return Principal("agent", agent_id)
        if token and not agent_key:
            raise HTTPException(status_code=401, detail="unknown credentials")
        if agent_key:
            raise HTTPException(status_code=401, detail="unknown agent key")
    return Principal("anonymous")


async def get_principal(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_sunny_agent_key: Optional[str] = Header(default=None),
) -> Principal:
    return resolve_principal(request.app.state.settings, request.app.state.store, authorization, x_sunny_agent_key)


def require_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin required")


def require_hub_user(principal: Principal) -> None:
    if not principal.is_hub_user:
        raise HTTPException(status_code=401, detail="hub login required")


def require_viewer(principal: Principal) -> None:
    if principal.is_admin or principal.is_developer or principal.is_agent:
        return
    raise HTTPException(status_code=401, detail="registered agent key or hub login required")


def require_registered_peer(principal: Principal) -> None:
    if principal.is_admin or principal.is_agent:
        return
    if principal.is_developer:
        raise HTTPException(status_code=403, detail="developers cannot perform this action")
    raise HTTPException(status_code=401, detail="registered agent key or admin token required")


def can_manage_card(principal: Principal, agent_id: str, created_by: Optional[str]) -> bool:
    if principal.is_admin:
        return True
    if principal.is_agent and principal.agent_id == agent_id:
        return True
    if principal.is_developer and principal.user_id and created_by and principal.user_id == created_by:
        return True
    return False


def can_delete_agent(principal: Principal, created_by: Optional[str]) -> bool:
    if principal.is_admin:
        return True
    if principal.is_developer and principal.user_id and created_by and principal.user_id == created_by:
        return True
    return False


def require_card_manager(principal: Principal, agent_id: str, created_by: Optional[str]) -> None:
    if not can_manage_card(principal, agent_id, created_by):
        raise HTTPException(status_code=403, detail="only admin or the creating developer can modify this agent")


def require_agent_owner(principal: Principal, created_by: Optional[str]) -> None:
    if not can_delete_agent(principal, created_by):
        raise HTTPException(status_code=403, detail="only admin or the creating developer can delete this agent")


def permissions_for(principal: Principal) -> Dict[str, bool]:
    admin = principal.is_admin
    hub = principal.is_hub_user
    return {
        "view_cards": hub or principal.is_agent,
        "publish": hub,
        "manage_all_agents": admin,
        "view_activity": admin,
        "view_graph": admin,
        "export_enroll_token": admin,
        "issue_keys": admin,
        "manage_users": admin,
        "disable_agents": admin,
        "issue_tickets": admin or principal.is_agent,
    }
