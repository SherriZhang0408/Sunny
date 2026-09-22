"""Thin JSON-RPC 2.0 MCP discovery surface. No tickets, no invoke."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from . import policy
from .a2a_export import public_card
from .join import WHEN_NOT_TO_USE, WHEN_TO_USE, build_join_payload
from .net import resolve_public_url
from .security import Principal, require_viewer

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "sunny-registry"
SERVER_VERSION = "0.2.0"

BLOCKED_TOOL_NAMES = frozenset(
    {
        "tickets",
        "invoke",
        "issue_ticket",
        "verify_ticket",
        "call",
        "sunny.invoke",
        "sunny.tickets",
    }
)

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_agents",
        "description": (
            "List online, peer-visible enterprise agents and their public skills. "
            "Includes access recipe (sidecar URL + ticket path). Does not issue tickets or keys."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "workspace": {"type": "string"},
                "q": {"type": "string"},
            },
        },
    },
    {
        "name": "search_registry",
        "description": "Search registered online read-only skills. Does not return invoke URLs, tickets, or keys.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "skill": {"type": "string"},
                "tag": {"type": "string"},
                "workspace": {"type": "string"},
                "q": {"type": "string"},
            },
        },
    },
    {
        "name": "get_card",
        "description": "Read the public SUNNY Card (restricted skills stripped) plus how to access it. Does not issue tickets.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["agent_id"],
            "properties": {"agent_id": {"type": "string", "minLength": 1}},
        },
    },
    {
        "name": "get_extended_card",
        "description": "Read the authenticated Extended Card. Requires sak_ or Hub session. No tickets or keys.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["agent_id"],
            "properties": {"agent_id": {"type": "string", "minLength": 1}},
        },
    },
    {
        "name": "describe_access",
        "description": (
            "Describe how a peer may access an agent or skill: sidecar URL, invoke path, "
            "and the REST ticket recipe. Does not issue a ticket or invoke."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["agent_id"],
            "properties": {
                "agent_id": {"type": "string", "minLength": 1},
                "skill_id": {"type": "string"},
            },
        },
    },
    {
        "name": "list_card_changes",
        "description": "Poll Card version bumps since an id. Does not return tickets or invoke anything.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "since": {"type": "integer", "minimum": 0},
                "agent_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        },
    },
    {
        "name": "join",
        "description": "Join packet summary: when to use SUNNY, how to self-register. Never includes the enroll token.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
]


def server_instructions() -> str:
    lines = [
        "SUNNY 是企业 Agent 注册中心的发现面。不替代本机 tools / skills，不签发调用票，不转发业务。",
        "看见名片不等于能调用。",
        "",
        "要来：",
    ]
    lines.extend("- {0}".format(item) for item in WHEN_TO_USE)
    lines.append("")
    lines.append("不要来：")
    lines.extend("- {0}".format(item) for item in WHEN_NOT_TO_USE)
    return "\n".join(lines)


def tool_catalog() -> Dict[str, Any]:
    return {
        "service": SERVER_NAME,
        "transport": "jsonrpc-2.0",
        "path": "/mcp",
        "stdio": "python3 -m sunny_registry.mcp_stdio",
        "protocolVersion": PROTOCOL_VERSION,
        "tools": [
            {"name": item["name"], "description": item["description"]}
            for item in TOOLS
        ],
        "instructions": server_instructions(),
        "notes": "POST JSON-RPC. Discovery only: no tickets issued, no invoke.",
    }


def _rpc_error(code: int, message: str, rpc_id: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}},
        status_code=status_code,
    )


def _rpc_result(rpc_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})


def _tool_text(payload: Any) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
    }


def _registry_base(settings, request: Optional[Request] = None) -> str:
    return resolve_public_url(
        getattr(settings, "public_url", "") or "",
        getattr(settings, "listen_host", "0.0.0.0"),
        int(getattr(settings, "listen_port", 8088)),
        request,
    )


def _sidecar_url(card: Dict[str, Any]) -> Optional[str]:
    for item in card.get("supportedInterfaces") or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if url:
                return url.rstrip("/")
    return None


def _skill_ext(skill: Any) -> Dict[str, Any]:
    if not isinstance(skill, dict):
        return {}
    ext = skill.get("x-sunny")
    return ext if isinstance(ext, dict) else {}


def _public_skill_view(skill: Dict[str, Any]) -> Dict[str, Any]:
    ext = _skill_ext(skill)
    return {
        "id": skill.get("id"),
        "name": skill.get("name"),
        "description": skill.get("description"),
        "tags": skill.get("tags") or [],
        "data_class": ext.get("data_class") or skill.get("data_class") or "internal",
        "side_effects": ext.get("side_effects") or "read",
        "when_not_to_use": list(ext.get("when_not_to_use") or []),
    }


def _invoke_parts(sidecar: Optional[str], skill: Optional[Dict[str, Any]]) -> Tuple[str, Optional[str], Optional[str]]:
    ext = _skill_ext(skill) if skill else {}
    invoke = ext.get("invoke") if isinstance(ext.get("invoke"), dict) else {}
    method = str(invoke.get("method") or "POST")
    path = str(invoke.get("path") or "").strip()
    skill_id = str((skill or {}).get("id") or "").strip()
    if not path and skill_id:
        path = "/sunny/invoke/{0}".format(skill_id)
    url = None
    if sidecar and path:
        parsed = urlparse(sidecar)
        if path.startswith("/"):
            url = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
        else:
            url = sidecar.rstrip("/") + "/" + path.lstrip("/")
    elif sidecar and skill_id:
        url = sidecar.rstrip("/") + "/invoke/" + skill_id
    return method, path or None, url


def _access_recipe(
    settings,
    request: Optional[Request],
    agent_id: str,
    card: Dict[str, Any],
    skill: Optional[Dict[str, Any]] = None,
    *,
    lifecycle: Optional[str] = None,
    discovery: Optional[str] = None,
) -> Dict[str, Any]:
    base = _registry_base(settings, request)
    sidecar = _sidecar_url(card)
    method, path, invoke_url = _invoke_parts(sidecar, skill)
    skill_id = str((skill or {}).get("id") or "").strip() or None
    denied = policy.ticket_denied_for_lifecycle(lifecycle)
    if denied is None and skill is not None:
        denied = policy.peer_ticket_denied(
            {
                "side_effects": _skill_ext(skill).get("side_effects") or "read",
                "data_class": _skill_ext(skill).get("data_class") or "internal",
            },
            discovery,
        )
    ticket_body = {"callee_id": agent_id}
    if skill_id:
        ticket_body["skill_id"] = skill_id
    return {
        "discovery_equals_access": False,
        "peer_may_request_ticket": denied is None,
        "reason": denied,
        "auth": "sunny_ticket",
        "ticket": {
            "method": "POST",
            "url": base.rstrip("/") + "/api/v1/tickets",
            "header": "X-Sunny-Agent-Key",
            "body": ticket_body,
        },
        "invoke": {
            "method": method,
            "sidecar_url": sidecar,
            "path": path,
            "url": invoke_url,
            "authorization": "Bearer <ticket>",
        },
        "notes": [
            "Registry 不转发业务请求。",
            "看见名片不等于能调用。先出票，再直打 sidecar。",
            "不要经 MCP 调用业务。",
        ],
    }


def _sanitize_search_item(item: Dict[str, Any]) -> Dict[str, Any]:
    skills = []
    for skill in item.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        skills.append(
            {
                "id": skill.get("id"),
                "name": skill.get("name"),
                "tags": skill.get("tags") or [],
                "data_class": skill.get("data_class") or "internal",
            }
        )
    return {
        "agent_id": item.get("agent_id"),
        "name": item.get("name"),
        "description": item.get("description"),
        "version": item.get("version"),
        "workspace": item.get("workspace"),
        "lifecycle": item.get("lifecycle"),
        "discovery": item.get("discovery"),
        "runtime_status": item.get("runtime_status"),
        "access_tier": item.get("access_tier"),
        "skill_count": len(skills),
        "skills": skills,
    }


def _catalog_item(
    detail: Dict[str, Any],
    card: Dict[str, Any],
    settings,
    request: Optional[Request],
) -> Dict[str, Any]:
    skills = []
    for skill in card.get("skills") or []:
        if isinstance(skill, dict):
            skills.append(_public_skill_view(skill))
    return {
        "agent_id": detail.get("agent_id"),
        "name": detail.get("name"),
        "description": detail.get("description"),
        "version": detail.get("version"),
        "workspace": detail.get("workspace"),
        "lifecycle": detail.get("lifecycle"),
        "discovery": detail.get("discovery"),
        "runtime_status": detail.get("runtime_status"),
        "access_tier": detail.get("access_tier"),
        "skill_count": len(skills),
        "skills": skills,
        "access": _access_recipe(
            settings,
            request,
            str(detail.get("agent_id") or ""),
            card,
            lifecycle=detail.get("lifecycle"),
            discovery=detail.get("discovery"),
        ),
    }


def _visible_detail(store, principal: Principal, agent_id: str) -> Dict[str, Any]:
    require_viewer(principal)
    detail = store.get_detail(agent_id)
    caller_ws = store.agent_workspace(principal.agent_id) if principal.is_agent else None
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


def _call_list(
    store,
    principal: Principal,
    arguments: Dict[str, Any],
    settings,
    request: Request,
) -> Dict[str, Any]:
    require_viewer(principal)
    caller_ws = store.agent_workspace(principal.agent_id) if principal.is_agent else None
    items = []
    for item in store.list_agents(
        include_disabled=False,
        only_registered=True,
        workspace=arguments.get("workspace") or None,
        q=arguments.get("q") or None,
        peer_visible_only=not principal.is_admin,
        include_owned_by=principal.user_id if principal.is_hub_user else None,
        include_agent_id=principal.agent_id if principal.is_agent else None,
        caller_workspace=caller_ws,
        enforce_scope=not principal.is_admin,
    ):
        if item.get("runtime_status") != "online":
            continue
        detail = store.get_detail(item["agent_id"])
        if not policy.can_view_agent(
            is_admin=principal.is_admin,
            is_owner=bool(principal.is_hub_user and principal.user_id and principal.user_id == detail.get("created_by")),
            is_self=bool(principal.is_agent and principal.agent_id == item["agent_id"]),
            lifecycle=detail["lifecycle"],
            discovery=detail.get("discovery"),
            collab_scope=detail.get("collab_scope") or "",
            caller_workspace=caller_ws,
            callee_workspace=detail.get("workspace"),
        ):
            continue
        card = public_card(detail.get("card") if isinstance(detail.get("card"), dict) else {})
        items.append(_catalog_item(detail, card, settings, request))
    return {
        "items": items,
        "count": len(items),
        "note": "Seeing a card is not permission to invoke. Use describe_access, then REST tickets.",
    }


def _call_search(store, principal: Principal, arguments: Dict[str, Any]) -> Dict[str, Any]:
    require_viewer(principal)
    only_alive = True
    caller_ws = store.agent_workspace(principal.agent_id) if principal.is_agent else None
    items = [
        _sanitize_search_item(item)
        for item in store.search(
            skill_id=arguments.get("skill") or None,
            tag=arguments.get("tag") or None,
            workspace=arguments.get("workspace") or None,
            q=arguments.get("q") or None,
            only_alive=only_alive,
            caller_workspace=caller_ws,
            enforce_scope=not principal.is_admin,
            include_owned_by=principal.user_id if principal.is_hub_user else None,
            include_agent_id=principal.agent_id if principal.is_agent else None,
        )
    ]
    return {"items": items, "count": len(items)}


def _call_get_card(
    store,
    principal: Principal,
    arguments: Dict[str, Any],
    settings,
    request: Request,
) -> Dict[str, Any]:
    agent_id = str(arguments.get("agent_id") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    detail = _visible_detail(store, principal, agent_id)
    card = public_card(detail.get("card") if isinstance(detail.get("card"), dict) else {})
    return {
        "agent_id": detail["agent_id"],
        "version": detail.get("version"),
        "card_view": "public",
        "card": card,
        "access": _access_recipe(
            settings,
            request,
            detail["agent_id"],
            card,
            lifecycle=detail.get("lifecycle"),
            discovery=detail.get("discovery"),
        ),
    }


def _call_get_extended(store, principal: Principal, arguments: Dict[str, Any]) -> Dict[str, Any]:
    agent_id = str(arguments.get("agent_id") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    detail = _visible_detail(store, principal, agent_id)
    card = detail.get("card") if isinstance(detail.get("card"), dict) else {}
    return {
        "agent_id": detail["agent_id"],
        "version": detail.get("version"),
        "card_view": "full",
        "card": card,
    }


def _call_describe_access(
    store,
    principal: Principal,
    arguments: Dict[str, Any],
    settings,
    request: Request,
) -> Dict[str, Any]:
    agent_id = str(arguments.get("agent_id") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    skill_id = str(arguments.get("skill_id") or "").strip()
    detail = _visible_detail(store, principal, agent_id)
    raw = detail.get("card") if isinstance(detail.get("card"), dict) else {}
    card = public_card(raw)
    chosen = None
    if skill_id:
        for skill in raw.get("skills") or []:
            if isinstance(skill, dict) and skill.get("id") == skill_id:
                chosen = skill
                break
        if chosen is None:
            raise HTTPException(status_code=404, detail="skill not found")
        public_ids = {
            skill.get("id")
            for skill in card.get("skills") or []
            if isinstance(skill, dict)
        }
        if skill_id not in public_ids:
            return {
                "agent_id": agent_id,
                "skill_id": skill_id,
                "visible": False,
                "access": _access_recipe(
                    settings,
                    request,
                    agent_id,
                    card,
                    chosen,
                    lifecycle=detail.get("lifecycle"),
                    discovery=detail.get("discovery"),
                ),
            }
    skills = []
    if chosen is not None:
        skills.append(_public_skill_view(chosen))
    else:
        for skill in card.get("skills") or []:
            if isinstance(skill, dict):
                skills.append(_public_skill_view(skill))
    return {
        "agent_id": agent_id,
        "skill_id": skill_id or None,
        "visible": True,
        "skills": skills,
        "access": _access_recipe(
            settings,
            request,
            agent_id,
            card,
            chosen,
            lifecycle=detail.get("lifecycle"),
            discovery=detail.get("discovery"),
        ),
    }


def _call_card_changes(store, principal: Principal, arguments: Dict[str, Any]) -> Dict[str, Any]:
    require_viewer(principal)
    since = arguments.get("since") or 0
    try:
        since_id = int(since)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="since must be an integer")
    limit = arguments.get("limit") or 100
    try:
        limit_n = int(limit)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="limit must be an integer")
    agent_id = arguments.get("agent_id") or None
    return store.list_card_changes(
        since_id=since_id,
        agent_id=str(agent_id).strip() if agent_id else None,
        peer_visible_only=not principal.is_admin,
        limit=limit_n,
    )


def _call_join(settings, request: Request) -> Dict[str, Any]:
    packet = build_join_payload(settings, request, include_token=False)
    enroll = dict(packet.get("enroll") or {})
    enroll.pop("token", None)
    enroll["token_included"] = False
    return {
        "service": packet.get("service"),
        "role": packet.get("role"),
        "description": packet.get("description"),
        "public_url": packet.get("public_url"),
        "join_md": packet.get("join_md"),
        "health": packet.get("health"),
        "mcp": packet.get("mcp"),
        "when_to_use": packet.get("when_to_use"),
        "when_not_to_use": packet.get("when_not_to_use"),
        "enroll": {
            "method": enroll.get("method"),
            "path": enroll.get("path"),
            "header": enroll.get("header"),
            "enrollment_source": enroll.get("enrollment_source"),
            "token_included": False,
        },
        "after_enroll": packet.get("after_enroll"),
        "rules": packet.get("rules"),
    }


def _dispatch_tool(
    name: str,
    arguments: Dict[str, Any],
    principal: Principal,
    store,
    settings,
    request: Request,
) -> Dict[str, Any]:
    if name in BLOCKED_TOOL_NAMES or name not in {item["name"] for item in TOOLS}:
        raise HTTPException(status_code=404, detail="unknown tool: {0}".format(name))
    if name != "join":
        require_viewer(principal)
    if name == "list_agents":
        return _call_list(store, principal, arguments, settings, request)
    if name == "search_registry":
        return _call_search(store, principal, arguments)
    if name == "get_card":
        return _call_get_card(store, principal, arguments, settings, request)
    if name == "get_extended_card":
        return _call_get_extended(store, principal, arguments)
    if name == "describe_access":
        return _call_describe_access(store, principal, arguments, settings, request)
    if name == "list_card_changes":
        return _call_card_changes(store, principal, arguments)
    return _call_join(settings, request)


def handle_jsonrpc(
    body: Any,
    principal: Principal,
    store,
    settings,
    request: Request,
) -> JSONResponse:
    if not isinstance(body, dict):
        return _rpc_error(-32600, "invalid request: object expected")
    rpc_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        return _rpc_error(-32600, "invalid request: jsonrpc must be 2.0", rpc_id)
    method = body.get("method")
    if not isinstance(method, str) or not method:
        return _rpc_error(-32600, "invalid request: method required", rpc_id)
    params = body.get("params") if isinstance(body.get("params"), dict) else {}

    if method == "ping":
        return _rpc_result(rpc_id, {})
    if method == "initialize":
        return _rpc_result(
            rpc_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": server_instructions(),
            },
        )
    if method == "notifications/initialized":
        return JSONResponse({"ok": True}, status_code=202)
    if method == "tools/list":
        return _rpc_result(rpc_id, {"tools": TOOLS})
    if method != "tools/call":
        return _rpc_error(-32601, "method not found: {0}".format(method), rpc_id)

    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if not name:
        return _rpc_error(-32602, "invalid params: tool name required", rpc_id)
    try:
        payload = _dispatch_tool(name, arguments, principal, store, settings, request)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        if exc.status_code in {401, 403, 404}:
            return _rpc_error(-32000 - exc.status_code, detail, rpc_id)
        return _rpc_error(-32602, detail, rpc_id)
    return _rpc_result(rpc_id, _tool_text(payload))
