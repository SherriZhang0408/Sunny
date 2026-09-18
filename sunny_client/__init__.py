"""Python client: search / get_card / ticket / invoke. Registry never proxies the call."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
import httpx


def invoke_url(card: dict, skill_id: str) -> str:
    interfaces = card.get("supportedInterfaces") or []
    if not interfaces:
        raise ValueError("card has no supportedInterfaces")
    base = interfaces[0]["url"].rstrip("/")
    origin = re.sub(r"/sunny/v1$", "", base)
    path = "/sunny/invoke/{0}".format(skill_id)
    for skill in card.get("skills") or []:
        if skill.get("id") == skill_id:
            ext = skill.get("x-sunny") or {}
            invoke = ext.get("invoke") or {}
            if invoke.get("path"):
                path = invoke["path"]
            break
    return origin.rstrip("/") + path


class SunnyClient:
    def __init__(
        self,
        registry_url: str,
        *,
        agent_key: Optional[str] = None,
        admin_token: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.registry_url = registry_url.rstrip("/")
        self.agent_key = agent_key
        self.admin_token = admin_token
        self._owns = client is None
        self.http = client or httpx.Client(timeout=15.0)

    def close(self) -> None:
        if self._owns:
            self.http.close()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.admin_token:
            headers["Authorization"] = "Bearer {0}".format(self.admin_token)
        elif self.agent_key:
            headers["X-Sunny-Agent-Key"] = self.agent_key
        return headers

    def search(self, skill: Optional[str] = None, tag: Optional[str] = None, q: Optional[str] = None) -> Dict[str, Any]:
        params = {}
        if skill:
            params["skill"] = skill
        if tag:
            params["tag"] = tag
        if q:
            params["q"] = q
        res = self.http.get("{0}/api/v1/search".format(self.registry_url), headers=self._headers(), params=params)
        res.raise_for_status()
        return res.json()

    def get_card(self, agent_id: str) -> Dict[str, Any]:
        res = self.http.get("{0}/api/v1/agents/{1}".format(self.registry_url, agent_id), headers=self._headers())
        res.raise_for_status()
        return res.json()

    def issue_ticket(self, callee_id: str, skill_id: str, caller_id: Optional[str] = None) -> Dict[str, Any]:
        body = {"callee_id": callee_id, "skill_id": skill_id}
        if caller_id:
            body["caller_id"] = caller_id
        res = self.http.post("{0}/api/v1/tickets".format(self.registry_url), headers=self._headers(), json=body)
        res.raise_for_status()
        return res.json()

    def report_invocation(
        self,
        callee_id: str,
        skill_id: str,
        status: str,
        ticket: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        res = self.http.post(
            "{0}/api/v1/invocations".format(self.registry_url),
            headers=self._headers(),
            json={
                "callee_id": callee_id,
                "skill_id": skill_id,
                "status": status,
                "ticket": ticket,
                "trace_id": trace_id,
            },
        )
        res.raise_for_status()
        return res.json()

    def invoke(
        self,
        skill_id: str,
        slots: dict,
        *,
        callee_id: Optional[str] = None,
        caller_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if callee_id:
            detail = self.get_card(callee_id)
        else:
            found = self.search(skill=skill_id)
            if not found.get("items"):
                raise RuntimeError("no registered agent offers {0}".format(skill_id))
            detail = self.get_card(found["items"][0]["agent_id"])
        card = detail["card"]
        agent_id = detail["agent_id"]
        ticket = self.issue_ticket(agent_id, skill_id, caller_id=caller_id)
        url = invoke_url(card, skill_id)
        res = self.http.post(
            url,
            headers={"Authorization": "Bearer {0}".format(ticket["ticket"]), "Content-Type": "application/json"},
            json={"slots": slots, "trace_id": slots.get("trace_id")},
        )
        status = "ok" if res.status_code == 200 else "error"
        body = {}
        try:
            body = res.json()
        except Exception:
            body = {"detail": res.text}
        try:
            self.report_invocation(
                agent_id,
                skill_id,
                status,
                ticket=ticket["ticket"],
                trace_id=body.get("trace_id") or slots.get("trace_id"),
            )
        except Exception:
            pass
        res.raise_for_status()
        body["_ticket"] = {"jti": ticket.get("jti"), "callee_id": agent_id}
        return body
