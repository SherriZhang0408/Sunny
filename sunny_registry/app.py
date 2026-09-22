"""FastAPI application: registry API + Hub admin UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, get_settings
from .db import connect
from . import fts, mcp, observe, policy, pull, security
from .a2a_export import (
    CACHE_PRIVATE,
    cached_json,
    card_etag,
    has_restricted_skills,
    is_restricted_skill,
    public_card,
    strip_sunny_extensions,
)
from .card_validate import extract_agent_id
from .join import build_join_payload, join_markdown_for
from .security import (
    Principal,
    can_delete_agent,
    can_manage_card,
    get_principal,
    permissions_for,
    require_admin,
    require_agent_owner,
    require_card_manager,
    require_hub_user,
    require_registered_peer,
    require_viewer,
)
from .store import Store, StoreError
from .sweep import start_sweep

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SITE_DIR = Path(__file__).resolve().parents[1] / "docs" / "site"
HELP_MEDIA = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class RegisterBody(BaseModel):
    card: Dict[str, Any]
    enrollment_source: str


class PullBody(BaseModel):
    url: str
    enrollment_source: Optional[str] = None
    agent_id: Optional[str] = None
    discovery: Optional[str] = None


class RejectBody(BaseModel):
    reason: str


class CardBody(BaseModel):
    card: Dict[str, Any]


class TicketBody(BaseModel):
    caller_id: Optional[str] = None
    callee_id: str
    skill_id: str


class VerifyBody(BaseModel):
    ticket: str
    callee_id: Optional[str] = None
    skill_id: Optional[str] = None


class InvocationBody(BaseModel):
    caller_id: Optional[str] = None
    callee_id: str
    skill_id: str
    status: str = "ok"
    trace_id: Optional[str] = None
    ticket: Optional[str] = None


class LoginBody(BaseModel):
    username: str
    password: str


class UserCreateBody(BaseModel):
    username: str
    password: str
    role: str = "developer"


class AgentPatchBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    skills: Optional[List[Dict[str, Any]]] = None
    add_skills: Optional[List[Dict[str, Any]]] = None
    remove_skill_ids: Optional[List[str]] = None
    update_skills: Optional[List[Dict[str, Any]]] = None


def _raise_store(exc: StoreError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _with_access(principal: Principal, item: Dict[str, Any]) -> Dict[str, Any]:
    created_by = item.get("created_by")
    item["can_manage"] = can_manage_card(principal, item.get("agent_id") or "", created_by)
    item["can_delete"] = can_delete_agent(principal, created_by)
    return item


def _is_owner(principal: Principal, item: Dict[str, Any]) -> bool:
    return bool(principal.is_hub_user and principal.user_id and principal.user_id == item.get("created_by"))


def _is_self_agent(principal: Principal, item: Dict[str, Any]) -> bool:
    return bool(principal.is_agent and principal.agent_id == item.get("agent_id"))


def _sees_full_card(principal: Principal, item: Dict[str, Any]) -> bool:
    return policy.can_read_full_card(
        is_admin=principal.is_admin,
        is_owner=_is_owner(principal, item),
        is_self=_is_self_agent(principal, item),
    )


def _public_skill_summaries(skills: Any) -> list:
    items = []
    for skill in skills or []:
        if not isinstance(skill, dict):
            continue
        if is_restricted_skill(skill):
            continue
        items.append(
            {
                "id": skill.get("id"),
                "name": skill.get("name"),
                "tags": skill.get("tags") or [],
                "data_class": skill.get("data_class") or "internal",
            }
        )
    return items


def _present_agent(principal: Principal, item: Dict[str, Any], *, full_card: bool = False) -> Dict[str, Any]:
    presented = dict(item)
    _with_access(principal, presented)
    card = presented.get("card") if isinstance(presented.get("card"), dict) else None
    show_full = full_card or _sees_full_card(principal, presented)
    presented["has_extended"] = has_restricted_skills(card) if card is not None else any(
        is_restricted_skill(skill) for skill in (presented.get("skills") or [])
    )
    presented["card_view"] = "full" if show_full else "public"
    if card is not None:
        presented["card"] = card if show_full else public_card(card)
        if not show_full:
            presented["skills"] = _public_skill_summaries(presented.get("skills"))
            presented["skill_count"] = len(presented["skills"])
    elif not show_full:
        presented["skills"] = _public_skill_summaries(presented.get("skills"))
        presented["skill_count"] = len(presented["skills"])
    return presented


def _me_payload(principal: Principal) -> Dict[str, Any]:
    return {
        "user_id": principal.user_id,
        "username": principal.username or ("admin" if principal.is_admin else None),
        "role": principal.kind if principal.is_hub_user else None,
        "kind": principal.kind,
        "permissions": permissions_for(principal),
    }


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stopper = start_sweep(app.state.store, app.state.settings)
        yield
        if stopper:
            stopper()

    app = FastAPI(title="SUNNY Registry", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = Store(connect(settings.db_path), settings)

    from .seed import seed_if_empty, seed_users

    seed_users(app.state.store)
    if settings.seed_on_empty:
        seed_if_empty(app.state.store)

    @app.exception_handler(StoreError)
    async def store_error_handler(_request: Request, exc: StoreError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/api/v1/health")
    def health(request: Request) -> Dict[str, Any]:
        packet = build_join_payload(settings, request, include_token=False)
        return {
            "ok": True,
            "service": "sunny-registry",
            "role": "enterprise_agent_registry",
            "agents": app.state.store.count_agents(),
            "public_url": packet["public_url"],
            "join": packet["join_md"],
            "sweep": {
                "interval_s": settings.sweep_s,
                "refresh_interval_s": settings.refresh_interval_s,
                "last": app.state.store.last_sweep,
            },
            "fts": {"ready": fts.available(app.state.store.conn)},
        }

    @app.post("/api/v1/auth/login")
    def login(body: LoginBody) -> Dict[str, Any]:
        user = app.state.store.authenticate_user(body.username, body.password)
        if not user:
            raise HTTPException(status_code=401, detail="invalid username or password")
        issued = security.issue_session(settings.ticket_secret, user, settings.session_ttl_s)
        principal = Principal(user["role"], user_id=user["user_id"], username=user["username"])
        return {
            "token": issued["token"],
            "expires_at": issued["expires_at"],
            "user": _me_payload(principal),
        }

    @app.get("/api/v1/auth/me")
    def me(principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_hub_user(principal)
        return _me_payload(principal)

    @app.get("/api/v1/users")
    def list_users(principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        items = app.state.store.list_users()
        return {"items": items, "count": len(items)}

    @app.post("/api/v1/users")
    def create_user(body: UserCreateBody, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return app.state.store.create_user(body.username, body.password, body.role)

    @app.delete("/api/v1/users/{user_id}")
    def delete_user(user_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        if principal.user_id and principal.user_id == user_id and app.state.store.count_admins() <= 1:
            raise HTTPException(status_code=409, detail="cannot delete the last admin")
        return app.state.store.delete_user(user_id)

    @app.get("/api/v1/join")
    def join_json(
        request: Request,
        include_token: bool = False,
        principal: Principal = Depends(get_principal),
    ) -> Dict[str, Any]:
        if include_token:
            require_admin(principal)
        return build_join_payload(settings, request, include_token=include_token)

    @app.get("/api/v1/join.md")
    def join_markdown(
        request: Request,
        include_token: bool = False,
        download: bool = False,
        principal: Principal = Depends(get_principal),
    ) -> PlainTextResponse:
        if include_token:
            require_admin(principal)
        headers = {}
        if download:
            headers["Content-Disposition"] = 'attachment; filename="sunny-join.md"'
        return PlainTextResponse(
            join_markdown_for(settings, request, include_token=include_token),
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )

    @app.post("/api/v1/agents")
    def register(
        body: RegisterBody,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> Dict[str, Any]:
        enroll = request.headers.get("x-sunny-enroll")
        if body.enrollment_source not in {"self", "hub"}:
            raise HTTPException(status_code=400, detail="enrollment_source must be self or hub")
        if body.enrollment_source == "hub":
            require_hub_user(principal)
            actor = principal.actor
        else:
            if not enroll or not security._cmp(enroll, settings.enroll_token):
                raise HTTPException(status_code=401, detail="valid X-Sunny-Enroll required for self register")
            actor = principal.actor if principal.is_hub_user else "agent:self"
        created_by = principal.user_id if principal.is_hub_user else None
        result = app.state.store.register(body.card, body.enrollment_source, actor, created_by=created_by)
        return _with_access(principal, result)

    @app.post("/api/v1/agents/pull")
    def pull_agent(
        body: PullBody,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> Dict[str, Any]:
        enroll = request.headers.get("x-sunny-enroll")
        has_enroll = bool(enroll and security._cmp(enroll, settings.enroll_token))
        source = (body.enrollment_source or "").strip() or ("hub" if principal.is_hub_user else "self")
        if source not in {"self", "hub"}:
            raise HTTPException(status_code=400, detail="enrollment_source must be self or hub")
        if source == "hub":
            require_hub_user(principal)
            actor = principal.actor
            created_by = principal.user_id
        elif principal.is_hub_user:
            actor = principal.actor
            created_by = principal.user_id
        elif has_enroll:
            actor = "agent:self"
            created_by = None
        else:
            raise HTTPException(status_code=401, detail="hub login or valid X-Sunny-Enroll required")
        overlay = (body.agent_id or "").strip() or None
        if overlay and not principal.is_admin:
            raise HTTPException(status_code=403, detail="only admin may set agent_id on pull")
        fetched = app.state.store.fetch_card_from_url(body.url)
        try:
            card = pull.apply_agent_id(fetched["card"], overlay)
        except pull.PullError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
        overlay_discovery = (body.discovery or "").strip() or None
        if overlay_discovery:
            if overlay_discovery not in policy.KNOWN_DISCOVERY:
                raise HTTPException(status_code=400, detail="discovery must be registered_peers, private, or approval_required")
            sunny = card.setdefault("x-sunny", {})
            if not isinstance(sunny, dict):
                raise HTTPException(status_code=400, detail="x-sunny must be an object")
            sunny["discovery"] = overlay_discovery
        agent_id = extract_agent_id(card)
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="x-sunny.agent_id missing; admin may pass agent_id in the pull body",
            )
        row = app.state.store.get_row(agent_id)
        if row:
            created = row["created_by"] if "created_by" in row.keys() else None
            if not can_manage_card(principal, agent_id, created):
                if principal.kind == "anonymous" or (
                    principal.is_agent and principal.agent_id != agent_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="agent already registered: {0}".format(agent_id),
                    )
                raise HTTPException(status_code=403, detail="cannot refresh this card")
            result = app.state.store.apply_pulled_update(
                agent_id,
                card,
                fetched["source_url"],
                actor,
                allow_promote=principal.is_admin,
            )
            return _with_access(principal, result)
        result = app.state.store.register(
            card,
            source,
            actor,
            created_by=created_by,
            source_url=fetched["source_url"],
            summary="registered via well-known pull",
        )
        app.state.store.record_event(
            "card",
            actor,
            callee_id=result["agent_id"],
            summary="pull create {0}".format(result["agent_id"]),
            detail={"source_url": fetched["source_url"]},
        )
        return _with_access(principal, result)

    @app.get("/api/v1/agents")
    def list_agents(
        principal: Principal = Depends(get_principal),
        q: Optional[str] = None,
        workspace: Optional[str] = None,
        enrollment_source: Optional[str] = None,
        runtime_status: Optional[str] = None,
        discovery: Optional[str] = None,
        approval_status: Optional[str] = None,
        include_disabled: bool = True,
    ) -> Dict[str, Any]:
        require_viewer(principal)
        only_registered = not principal.is_admin
        caller_ws = app.state.store.agent_workspace(principal.agent_id) if principal.is_agent else None
        items = app.state.store.list_agents(
            include_disabled=include_disabled if principal.is_admin else False,
            only_registered=only_registered,
            q=q,
            workspace=workspace,
            enrollment_source=enrollment_source,
            runtime_status=runtime_status,
            discovery=discovery,
            approval_status=approval_status,
            peer_visible_only=not principal.is_admin,
            include_owned_by=principal.user_id if principal.is_hub_user else None,
            include_agent_id=principal.agent_id if principal.is_agent else None,
            caller_workspace=caller_ws,
            enforce_scope=not principal.is_admin,
        )
        items = [_present_agent(principal, item) for item in items]
        return {"items": items, "count": len(items)}

    def _visible_detail(agent_id: str, principal: Principal) -> Dict[str, Any]:
        require_viewer(principal)
        detail = app.state.store.get_detail(agent_id)
        caller_ws = app.state.store.agent_workspace(principal.agent_id) if principal.is_agent else None
        if not policy.can_view_agent(
            is_admin=principal.is_admin,
            is_owner=bool(principal.is_hub_user and principal.user_id and principal.user_id == detail.get("created_by")),
            is_self=bool(principal.is_agent and principal.agent_id == agent_id),
            lifecycle=detail["lifecycle"],
            discovery=detail.get("discovery"),
            collab_scope=detail.get("collab_scope") or "",
            caller_workspace=caller_ws,
            callee_workspace=detail.get("workspace"),
        ):
            raise HTTPException(status_code=404, detail="agent not found")
        return detail

    @app.get("/api/v1/agents/{agent_id}")
    def get_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        return _present_agent(principal, _visible_detail(agent_id, principal))

    @app.get("/api/v1/agents/{agent_id}/extended")
    def get_agent_extended(
        agent_id: str,
        request: Request,
        principal: Principal = Depends(get_principal),
    ):
        detail = _visible_detail(agent_id, principal)
        card = detail.get("card") if isinstance(detail.get("card"), dict) else {}
        presented = _present_agent(principal, detail, full_card=True)
        return cached_json(
            request,
            presented,
            card_etag(card),
            CACHE_PRIVATE,
            vary="Authorization",
        )

    @app.get("/api/v1/agents/{agent_id}/a2a")
    def get_agent_a2a(
        agent_id: str,
        request: Request,
        principal: Principal = Depends(get_principal),
    ):
        detail = _visible_detail(agent_id, principal)
        card = detail.get("card") if isinstance(detail.get("card"), dict) else {}
        return cached_json(
            request,
            strip_sunny_extensions(public_card(card)),
            card_etag(card),
            CACHE_PRIVATE,
            vary="Authorization",
        )

    @app.put("/api/v1/agents/{agent_id}")
    def update_agent(
        agent_id: str,
        body: CardBody,
        principal: Principal = Depends(get_principal),
    ) -> Dict[str, Any]:
        row = app.state.store.get_row(agent_id)
        if not row:
            raise HTTPException(status_code=404, detail="agent not found")
        require_card_manager(principal, agent_id, row["created_by"] if "created_by" in row.keys() else None)
        return _with_access(
            principal,
            app.state.store.update_card(
                agent_id,
                body.card,
                principal.actor,
                allow_promote=principal.is_admin,
            ),
        )

    @app.patch("/api/v1/agents/{agent_id}")
    def patch_agent(
        agent_id: str,
        body: AgentPatchBody,
        principal: Principal = Depends(get_principal),
    ) -> Dict[str, Any]:
        row = app.state.store.get_row(agent_id)
        if not row:
            raise HTTPException(status_code=404, detail="agent not found")
        require_card_manager(principal, agent_id, row["created_by"] if "created_by" in row.keys() else None)
        patch = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
        return _with_access(
            principal,
            app.state.store.patch_card(
                agent_id,
                patch,
                principal.actor,
                allow_promote=principal.is_admin,
            ),
        )

    @app.delete("/api/v1/agents/{agent_id}")
    def delete_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        row = app.state.store.get_row(agent_id)
        if not row:
            raise HTTPException(status_code=404, detail="agent not found")
        require_agent_owner(principal, row["created_by"] if "created_by" in row.keys() else None)
        return app.state.store.delete_agent(agent_id, principal.actor)

    @app.post("/api/v1/agents/{agent_id}/disable")
    def disable_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return app.state.store.set_lifecycle(agent_id, "disabled", principal.actor)

    @app.post("/api/v1/agents/{agent_id}/deprecate")
    def deprecate_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return app.state.store.set_lifecycle(agent_id, "deprecated", principal.actor)

    @app.post("/api/v1/agents/{agent_id}/enable")
    def enable_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return app.state.store.set_lifecycle(agent_id, "registered", principal.actor)

    @app.post("/api/v1/agents/{agent_id}/keys")
    def issue_agent_key(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return app.state.store.issue_agent_key(agent_id, principal.actor)

    @app.post("/api/v1/agents/{agent_id}/heartbeat")
    def heartbeat(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        if not (principal.is_admin or principal.agent_id == agent_id):
            raise HTTPException(status_code=403, detail="heartbeat must use this agent's key")
        return app.state.store.heartbeat(agent_id, principal.actor)

    @app.get("/api/v1/agents/{agent_id}/revisions")
    def revisions(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_viewer(principal)
        return {"items": app.state.store.revisions(agent_id)}

    @app.get("/api/v1/agents/{agent_id}/revisions/{rev}")
    def revision_card(agent_id: str, rev: int, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return app.state.store.revision_card(agent_id, rev)

    @app.post("/api/v1/agents/{agent_id}/probe")
    def probe_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        if not (principal.is_admin or principal.agent_id == agent_id):
            raise HTTPException(status_code=403, detail="probe must use admin or this agent's key")
        return _with_access(principal, app.state.store.probe_agent(agent_id, principal.actor))

    @app.post("/api/v1/agents/{agent_id}/refresh")
    def refresh_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        row = app.state.store.get_row(agent_id)
        if not row:
            raise HTTPException(status_code=404, detail="agent not found")
        require_card_manager(
            principal,
            agent_id,
            row["created_by"] if "created_by" in row.keys() else None,
        )
        return _with_access(principal, app.state.store.refresh_from_source(agent_id, principal.actor))

    @app.get("/api/v1/approvals")
    def list_approvals(
        principal: Principal = Depends(get_principal),
        status: str = Query(default="pending"),
    ) -> Dict[str, Any]:
        require_admin(principal)
        items = [
            _with_access(principal, item)
            for item in app.state.store.list_approvals(status=status)
        ]
        return {"items": items, "count": len(items), "status": status}

    @app.post("/api/v1/agents/{agent_id}/approve")
    def approve_agent(agent_id: str, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return _with_access(principal, app.state.store.approve_agent(agent_id, principal.actor))

    @app.post("/api/v1/agents/{agent_id}/reject")
    def reject_agent(
        agent_id: str,
        body: RejectBody,
        principal: Principal = Depends(get_principal),
    ) -> Dict[str, Any]:
        require_admin(principal)
        return _with_access(principal, app.state.store.reject_agent(agent_id, principal.actor, body.reason))

    @app.get("/api/v1/search")
    def search(
        principal: Principal = Depends(get_principal),
        skill: Optional[str] = Query(default=None),
        tag: Optional[str] = Query(default=None),
        workspace: Optional[str] = Query(default=None),
        q: Optional[str] = Query(default=None),
        alive: bool = Query(default=True),
    ) -> Dict[str, Any]:
        require_viewer(principal)
        only_alive = True if not principal.is_admin else bool(alive)
        caller_ws = app.state.store.agent_workspace(principal.agent_id) if principal.is_agent else None
        items = [
            _present_agent(principal, item)
            for item in app.state.store.search(
                skill_id=skill,
                tag=tag,
                workspace=workspace,
                q=q,
                only_alive=only_alive,
                caller_workspace=caller_ws,
                enforce_scope=not principal.is_admin,
                include_owned_by=principal.user_id if principal.is_hub_user else None,
                include_agent_id=principal.agent_id if principal.is_agent else None,
            )
        ]
        hits = [item["agent_id"] for item in items]
        caller_id = principal.agent_id if principal.is_agent else None
        app.state.store.record_event(
            "search",
            principal.actor,
            caller_id=caller_id,
            skill_id=skill,
            summary="search hits={0}".format(len(hits)),
            detail=observe.search_detail(skill, tag, workspace, q, hits, len(hits)),
        )
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/card-changes")
    def list_card_changes(
        principal: Principal = Depends(get_principal),
        since: int = Query(default=0),
        agent_id: Optional[str] = Query(default=None),
        limit: int = Query(default=100),
    ) -> Dict[str, Any]:
        require_viewer(principal)
        caller_ws = app.state.store.agent_workspace(principal.agent_id) if principal.is_agent else None
        return app.state.store.list_card_changes(
            since_id=since,
            agent_id=agent_id,
            peer_visible_only=not principal.is_admin,
            limit=limit,
            caller_workspace=caller_ws,
            enforce_scope=not principal.is_admin,
            include_owned_by=principal.user_id if principal.is_hub_user else None,
            include_agent_id=principal.agent_id if principal.is_agent else None,
        )

    @app.post("/api/v1/tickets")
    def issue_ticket(body: TicketBody, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_registered_peer(principal)
        caller = body.caller_id
        if principal.is_agent:
            caller = principal.agent_id
        if not caller:
            raise HTTPException(status_code=400, detail="caller_id required")
        if principal.is_agent and caller != principal.agent_id:
            raise HTTPException(status_code=403, detail="caller must be the authenticated agent")
        callee = app.state.store.get_detail(body.callee_id)
        lifecycle_denied = policy.ticket_denied_for_lifecycle(callee["lifecycle"])
        if lifecycle_denied:
            app.state.store.record_event(
                "ticket",
                principal.actor,
                status="denied",
                caller_id=caller,
                callee_id=body.callee_id,
                skill_id=body.skill_id,
                summary="ticket denied: {0}".format(lifecycle_denied),
                detail={"reason": lifecycle_denied},
            )
            raise HTTPException(status_code=409, detail=lifecycle_denied)
        skill = app.state.store.skill_on_agent(body.callee_id, body.skill_id)
        if not skill:
            app.state.store.record_event(
                "ticket",
                principal.actor,
                status="denied",
                caller_id=caller,
                callee_id=body.callee_id,
                skill_id=body.skill_id,
                summary="ticket denied: skill not on card",
                detail={"reason": "skill not on callee card"},
            )
            raise HTTPException(status_code=404, detail="skill not on callee card")
        if not principal.is_admin:
            denied = policy.peer_ticket_denied(skill, callee.get("discovery"))
            if not denied:
                caller_row = app.state.store.get_row(caller)
                denied = policy.scope_ticket_denied(
                    callee.get("collab_scope"),
                    caller_row["workspace"] if caller_row else None,
                    callee.get("workspace"),
                )
            if denied:
                app.state.store.record_event(
                    "ticket",
                    principal.actor,
                    status="denied",
                    caller_id=caller,
                    callee_id=body.callee_id,
                    skill_id=body.skill_id,
                    summary="ticket denied: {0}".format(denied),
                    detail={"reason": denied},
                )
                raise HTTPException(status_code=403, detail=denied)
        issued = security.issue_ticket(
            settings.ticket_secret,
            caller,
            body.callee_id,
            body.skill_id,
            settings.ticket_ttl_s,
            card_version=callee.get("version"),
        )
        app.state.store.record_ticket(issued["payload"])
        return {
            "ticket": issued["ticket"],
            "expires_at": issued["expires_at"],
            "caller_id": caller,
            "callee_id": body.callee_id,
            "skill_id": body.skill_id,
            "card_version": callee.get("version"),
            "jti": issued["jti"],
        }

    @app.post("/api/v1/tickets/verify")
    def verify_ticket(body: VerifyBody, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_registered_peer(principal)
        payload = security.verify_ticket(settings.ticket_secret, body.ticket)
        if body.callee_id and body.callee_id != payload["callee"]:
            raise HTTPException(status_code=403, detail="ticket callee mismatch")
        if body.skill_id and body.skill_id != payload["skill"]:
            raise HTTPException(status_code=403, detail="ticket skill mismatch")
        if principal.is_agent and principal.agent_id not in {payload["caller"], payload["callee"]}:
            raise HTTPException(status_code=403, detail="ticket not for this agent")
        callee = app.state.store.get_row(payload["callee"])
        if not callee or not policy.can_verify_ticket(callee["lifecycle"]):
            raise HTTPException(status_code=409, detail="callee is not registered")
        if policy.ticket_version_stale(payload.get("card_version"), callee["version"]):
            raise HTTPException(status_code=401, detail="ticket stale: card version changed")
        if app.state.store.ticket_is_revoked(payload["jti"]):
            raise HTTPException(status_code=401, detail="ticket revoked")
        return {"ok": True, "payload": payload}

    @app.post("/api/v1/invocations")
    def record_invocation(body: InvocationBody, principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_registered_peer(principal)
        caller = body.caller_id
        if principal.is_agent:
            caller = principal.agent_id
        if not caller:
            raise HTTPException(status_code=400, detail="caller_id required")
        ticket_jti = None
        if body.ticket:
            payload = security.verify_ticket(settings.ticket_secret, body.ticket)
            if payload["caller"] != caller or payload["callee"] != body.callee_id or payload["skill"] != body.skill_id:
                raise HTTPException(status_code=403, detail="ticket does not match invocation")
            ticket_jti = payload["jti"]
        return app.state.store.record_invocation(
            caller, body.callee_id, body.skill_id, body.status, body.trace_id, ticket_jti, principal.actor
        )

    @app.get("/api/v1/graph")
    def graph(principal: Principal = Depends(get_principal)) -> Dict[str, Any]:
        require_admin(principal)
        return app.state.store.graph()

    @app.get("/api/v1/activity")
    def activity(
        principal: Principal = Depends(get_principal),
        limit: int = 80,
        kind: Optional[str] = Query(default=None),
        trace_id: Optional[str] = Query(default=None),
        q: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        require_admin(principal)
        items = app.state.store.activity(
            limit=min(limit, 200),
            kind=kind or None,
            trace_id=trace_id or None,
            q=q or None,
        )
        return {"items": items, "count": len(items)}

    @app.get("/mcp")
    def mcp_info() -> Dict[str, Any]:
        return mcp.tool_catalog()

    @app.post("/mcp")
    async def mcp_rpc(request: Request, principal: Principal = Depends(get_principal)):
        try:
            body = await request.json()
        except Exception:
            return mcp.handle_jsonrpc(
                None, principal, app.state.store, app.state.settings, request
            )
        return mcp.handle_jsonrpc(body, principal, app.state.store, app.state.settings, request)

    if SITE_DIR.is_dir():
        def _help_file(path: Path) -> FileResponse:
            media = HELP_MEDIA.get(path.suffix.lower())
            if media:
                return FileResponse(str(path), media_type=media)
            return FileResponse(str(path))

        def _help_from_rel(rel: str) -> FileResponse:
            root = SITE_DIR.resolve()
            candidate = (SITE_DIR / rel).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                raise HTTPException(status_code=404, detail="not found")
            if candidate.is_dir():
                candidate = candidate / "index.html"
            if candidate.is_file():
                return _help_file(candidate)
            raise HTTPException(status_code=404, detail="not found")

        @app.get("/help", include_in_schema=False)
        def help_root() -> RedirectResponse:
            return RedirectResponse(url="/help/", status_code=307)

        @app.get("/help/", include_in_schema=False)
        def help_index() -> FileResponse:
            return _help_from_rel("index.html")

        @app.get("/help/{path:path}", include_in_schema=False)
        def help_page(path: str) -> FileResponse:
            rel = path.rstrip("/") + "/index.html" if path.endswith("/") else path
            if not rel:
                rel = "index.html"
            return _help_from_rel(rel)

    if WEB_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")

        def _html(path: Path) -> FileResponse:
            return FileResponse(str(path), media_type="text/html; charset=utf-8")

        @app.get("/")
        def admin_index() -> FileResponse:
            return _html(WEB_DIR / "index.html")

        @app.get("/{path:path}")
        def admin_spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            candidate = WEB_DIR / path
            if candidate.is_file():
                media = "text/html; charset=utf-8" if candidate.suffix == ".html" else None
                if media:
                    return FileResponse(str(candidate), media_type=media)
                return FileResponse(str(candidate))
            return _html(WEB_DIR / "index.html")

    return app


app = create_app()
