"""Optional Hermes skills: sunny.discover / sunny.invoke.

Default off. Does not change the Hermes kernel. Image / closed-loop Chat
routing stays on local adapters — never through SUNNY. Agent keys come from
env or a service file, never personal scratch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from . import SunnyClient

ENABLED_VARS = ("AIDATA_SUNNY", "SUNNY_HERMES_SKILLS")
DEFAULT_CALLER = "aidata.hermes"
DEFAULT_REGISTRY = "http://127.0.0.1:8088"

# Local Chat skills that must stay hardcoded (research §5.2).
# Include dotted ids, Hermes folder names (hyphens), and both separators as prefixes.
_BLOCKED_DOT_IDS = (
    "es.query_ai_collect",
    "cvat.create_special_task",
    "kb.retrieve",
    "db.query_scenes",
    "db.query_by_device",
    "db.query_lifecycle",
    "html.report",
    "memory.working",
    "memory.facts",
    "label.task.catalog",
    "session.scratch",
    "pet.suction.analysis",
    "aidata.env",
    "sunny.discover",
    "sunny.invoke",
)
_BLOCKED_HERMES_NAMES = (
    "es-query-ai-collect",
    "cvat-create-special-task",
    "kb-retrieve",
    "db-query-scenes",
    "db-query-by-device",
    "db-query-lifecycle",
    "html-report",
    "working-memory",
    "memory-facts",
    "label-task-catalog",
    "session-scratch",
    "pet-suction-analysis",
    "aidata-env",
    "sunny-discover",
    "sunny-invoke",
)
BLOCKED_SKILL_IDS = frozenset(_BLOCKED_DOT_IDS + _BLOCKED_HERMES_NAMES)
BLOCKED_SKILL_PREFIXES = (
    "es.",
    "es-",
    "cvat.",
    "cvat-",
    "kb.",
    "kb-",
    "db.",
    "db-",
    "image.",
    "image-",
    "memory.",
    "memory-",
    "html.",
    "html-",
    "label.",
    "label-",
    "session.",
    "session-",
    "pet.",
    "pet-",
    "aidata.",
    "aidata-",
    "sunny.",
    "sunny-",
    "working-",
)

_SAFE_ITEM_KEYS = (
    "agent_id",
    "name",
    "description",
    "version",
    "workspace",
    "lifecycle",
    "discovery",
    "runtime_status",
    "access_tier",
    "skill_count",
    "skills",
)
_SECRET_KEYS = frozenset(
    {
        "ticket",
        "agent_key",
        "authorization",
        "password",
        "secret",
        "api_key",
        "token",
    }
)

_OFF_HINT = (
    "跨 Agent 发现/调用时设 AIDATA_SUNNY=1，并用 SUNNY_AGENT_KEY"
    "（服务账号，不进 ~/.hermes/scratch）。图像/闭环仍走本机 Skill。"
)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def skills_enabled() -> bool:
    return any(_truthy(name) for name in ENABLED_VARS)


def registry_url() -> str:
    return os.environ.get("SUNNY_REGISTRY_URL", DEFAULT_REGISTRY).rstrip("/")


def caller_id() -> str:
    return os.environ.get("SUNNY_CALLER_ID", DEFAULT_CALLER).strip() or DEFAULT_CALLER


def is_scratch_path(path: str) -> bool:
    parts = [part.lower() for part in Path(path).expanduser().parts]
    return "scratch" in parts


def load_agent_key() -> str:
    key = os.environ.get("SUNNY_AGENT_KEY", "").strip()
    if key:
        return key
    raw_path = os.environ.get("SUNNY_AGENT_KEY_FILE", "").strip()
    if not raw_path:
        return ""
    if is_scratch_path(raw_path):
        raise ValueError("SUNNY_AGENT_KEY_FILE 不能指向个人 scratch")
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise ValueError("SUNNY_AGENT_KEY_FILE 不存在")
    return path.read_text(encoding="utf-8").strip()


def is_blocked_skill(skill_id: str) -> bool:
    sid = (skill_id or "").strip().lower()
    if not sid:
        return False
    compact = sid.replace("_", "-")
    if sid in BLOCKED_SKILL_IDS or compact in BLOCKED_SKILL_IDS:
        return True
    if compact.replace(".", "-") in BLOCKED_SKILL_IDS:
        return True
    return any(sid.startswith(prefix) or compact.startswith(prefix) for prefix in BLOCKED_SKILL_PREFIXES)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lower = str(key).lower()
            if lower in _SECRET_KEYS or lower.endswith("_token") or lower.endswith("_key"):
                continue
            if key == "_ticket":
                if isinstance(item, dict):
                    out[key] = {"jti": item.get("jti"), "callee_id": item.get("callee_id")}
                continue
            out[key] = sanitize(item)
        return out
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def summarize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if item.get("card") and not item.get("skills"):
        card = item.get("card") or {}
        skills = []
        for skill in card.get("skills") or []:
            skills.append(
                {
                    "id": skill.get("id"),
                    "name": skill.get("name"),
                    "tags": skill.get("tags") or [],
                }
            )
        base = {
            "agent_id": item.get("agent_id"),
            "name": item.get("name") or card.get("name"),
            "description": item.get("description") or card.get("description"),
            "version": item.get("version") or card.get("version"),
            "workspace": item.get("workspace") or (card.get("x-sunny") or {}).get("workspace"),
            "lifecycle": item.get("lifecycle"),
            "discovery": item.get("discovery") or (card.get("x-sunny") or {}).get("discovery"),
            "runtime_status": item.get("runtime_status"),
            "access_tier": item.get("access_tier") or (card.get("x-sunny") or {}).get("access_tier"),
            "skill_count": item.get("skill_count") if item.get("skill_count") is not None else len(skills),
            "skills": skills,
        }
        return sanitize(base)
    out = {}
    for key in _SAFE_ITEM_KEYS:
        if key in item:
            out[key] = item[key]
    if "skills" in out:
        clean_skills = []
        for skill in out.get("skills") or []:
            if not isinstance(skill, dict):
                continue
            clean_skills.append(
                {
                    "id": skill.get("id"),
                    "name": skill.get("name"),
                    "tags": skill.get("tags") or [],
                }
            )
        out["skills"] = clean_skills
    return sanitize(out)


def _off_payload(skill: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body = {
        "ready": False,
        "mock": False,
        "items": [],
        "result": None,
        "meta": {
            "skill": skill,
            "message": "{0} 默认关闭".format(skill),
            "fallback_hint": _OFF_HINT,
        },
    }
    if extra:
        body["meta"].update(extra)
    return body


def _not_ready(skill: str, message: str, hint: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    meta = {
        "skill": skill,
        "message": message,
        "fallback_hint": hint or _OFF_HINT,
    }
    meta.update(extra)
    return {
        "ready": False,
        "mock": False,
        "items": [],
        "result": None,
        "meta": meta,
    }


def _client(existing: Optional[SunnyClient]) -> Tuple[Optional[SunnyClient], bool]:
    if existing is not None:
        return existing, False
    key = load_agent_key()
    if not key:
        return None, False
    return SunnyClient(registry_url(), agent_key=key), True


def discover(
    skill: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    workspace: Optional[str] = None,
    agent_id: Optional[str] = None,
    client: Optional[SunnyClient] = None,
) -> Dict[str, Any]:
    if not skills_enabled():
        return _off_payload("sunny.discover")
    owned = False
    http = None
    try:
        http, owned = _client(client)
        if http is None:
            return _not_ready("sunny.discover", "缺少 SUNNY_AGENT_KEY（服务账号，不进 scratch）")
        if agent_id:
            items = [summarize_item(http.get_card(agent_id))]
        else:
            found = http.search(skill=skill, tag=tag, q=q, workspace=workspace)
            items = [summarize_item(item) for item in found.get("items") or []]
        return {
            "ready": True,
            "mock": False,
            "items": items,
            "result": None,
            "meta": {
                "skill": "sunny.discover",
                "count": len(items),
                "message": "目录命中 {0} 个已登记 Agent".format(len(items)),
            },
        }
    except Exception as exc:
        return _not_ready("sunny.discover", str(exc))
    finally:
        if owned and http is not None:
            http.close()


def invoke_peer(
    skill_id: str,
    slots: Optional[Dict[str, Any]] = None,
    *,
    callee_id: Optional[str] = None,
    caller: Optional[str] = None,
    client: Optional[SunnyClient] = None,
) -> Dict[str, Any]:
    if not skills_enabled():
        return _off_payload("sunny.invoke")
    sid = (skill_id or "").strip()
    if not sid:
        return _not_ready("sunny.invoke", "skill_id 不能为空")
    if is_blocked_skill(sid):
        return _not_ready(
            "sunny.invoke",
            "禁止经 SUNNY 调用本机技能 {0}。图像/闭环/知识/场景库走现有适配器。".format(sid),
            hint="改用 skills/adapters 里对应的本机 Skill，不要走 sunny.invoke",
        )
    if slots is None:
        slots = {}
    if not isinstance(slots, dict):
        return _not_ready("sunny.invoke", "slots 必须是 JSON 对象")
    slots = dict(slots)
    who = (caller or caller_id()).strip() or DEFAULT_CALLER
    owned = False
    http = None
    try:
        http, owned = _client(client)
        if http is None:
            return _not_ready("sunny.invoke", "缺少 SUNNY_AGENT_KEY（服务账号，不进 scratch）")
        target = (callee_id or "").strip() or None
        if not target:
            found = http.search(skill=sid)
            hits = found.get("items") or []
            if not hits:
                return _not_ready("sunny.invoke", "目录里没有提供 {0} 的已登记 Agent".format(sid))
            target = hits[0].get("agent_id")
        if target == who:
            return _not_ready(
                "sunny.invoke",
                "禁止经 SUNNY 调用自己（{0}），避免绕回本机 sidecar。".format(who),
                hint="本机技能走现有适配器；sunny.invoke 只调对等 Agent",
            )
        raw = http.invoke(sid, slots, callee_id=target, caller_id=who)
        clean = sanitize(raw)
        ticket = clean.get("_ticket") if isinstance(clean, dict) else None
        return {
            "ready": bool(clean.get("ready", True)) if isinstance(clean, dict) else True,
            "mock": bool(clean.get("mock", False)) if isinstance(clean, dict) else False,
            "items": [],
            "result": clean,
            "meta": {
                "skill": "sunny.invoke",
                "skill_id": sid,
                "callee_id": target,
                "caller_id": who,
                "ticket_jti": (ticket or {}).get("jti") if isinstance(ticket, dict) else None,
                "message": "已按 skill id 直打对方 sidecar（Registry 不转发）",
            },
        }
    except Exception as exc:
        return _not_ready("sunny.invoke", str(exc), skill_id=sid, caller_id=who)
    finally:
        if owned and http is not None:
            http.close()


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Optional Hermes sunny.discover / sunny.invoke (default off)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="Search the registry directory")
    d.add_argument("--skill", default="")
    d.add_argument("--tag", default="")
    d.add_argument("--q", default="")
    d.add_argument("--workspace", default="")
    d.add_argument("--agent", default="")
    inv = sub.add_parser("invoke", help="Issue a ticket and call a peer sidecar")
    inv.add_argument("--skill", required=True)
    inv.add_argument("--slots", default="{}")
    inv.add_argument("--callee", default="")
    inv.add_argument("--caller", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd == "discover":
        out = discover(
            skill=args.skill or None,
            tag=args.tag or None,
            q=args.q or None,
            workspace=args.workspace or None,
            agent_id=args.agent or None,
        )
    else:
        try:
            slots = json.loads(args.slots)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if not isinstance(slots, dict):
            print("slots must be a JSON object", file=sys.stderr)
            return 1
        out = invoke_peer(
            args.skill,
            slots,
            callee_id=args.callee or None,
            caller=args.caller or None,
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
