from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry import security

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP_JS = WEB / "assets" / "app.js"
APP_CSS = WEB / "assets" / "app.css"
INDEX = WEB / "index.html"

LOGIC_FNS = (
    "safeLoginNext",
    "loginHash",
    "intendedRoutePath",
    "loginErrorText",
    "motionReduced",
    "roleLabel",
)


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "hub-login.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.session_ttl_s = 3600
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _extract_js_function(src: str, name: str) -> str:
    token = "function " + name + "("
    start = src.find(token)
    if start < 0:
        raise AssertionError("app.js 缺少 function " + name)
    brace = src.find("{", start)
    depth = 0
    in_str = None
    escape = False
    for idx in range(brace, len(src)):
        ch = src[idx]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : idx + 1]
    raise AssertionError("function " + name + " 花括号不配对")


def _node_bin() -> str:
    path = shutil.which("node")
    if not path:
        pytest.fail("需要本机 node 才能执行登录页逻辑测试")
    return path


def _run_login_logic(tmp_path: Path):
    src = APP_JS.read_text(encoding="utf-8")
    extracted = "\n\n".join(_extract_js_function(src, name) for name in LOGIC_FNS)
    harness = r"""
function fail(msg) { throw new Error(msg); }
function eq(actual, expected, msg) {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) fail((msg || "assert") + " expected " + right + " got " + left);
}
function r(parts, qs) {
  return { parts: parts, query: new URLSearchParams(qs || "") };
}
function afterLoginDest(next) {
  return "#/" + safeLoginNext(next);
}
function gateHash(parts, qs) {
  return loginHash(intendedRoutePath(r(parts, qs)));
}
function withMotion(mode, prefersReduce) {
  global.document = {
    documentElement: {
      getAttribute: function () { return mode; }
    }
  };
  global.window = {
    matchMedia: function () { return { matches: !!prefersReduce }; }
  };
  return motionReduced();
}

eq(safeLoginNext(""), "explore", "empty next");
eq(safeLoginNext(null), "explore", "null next");
eq(safeLoginNext(undefined), "explore", "undefined next");
eq(safeLoginNext("login"), "explore", "login not a dest");
eq(safeLoginNext("https://evil.example"), "explore", "absolute rejected");
eq(safeLoginNext("http://evil.example/x"), "explore", "http rejected");
eq(safeLoginNext("javascript:alert(1)"), "explore", "javascript rejected");
eq(safeLoginNext("//evil"), "explore", "protocol-relative rejected");
eq(safeLoginNext("foo\\bar"), "explore", "backslash rejected");
eq(safeLoginNext("unknown"), "explore", "unknown section");
eq(safeLoginNext("publish/hub"), "publish/hub", "publish kept");
eq(safeLoginNext("explore?q=hermes"), "explore?q=hermes", "search kept");
eq(safeLoginNext("#/agents/aidata.hermes"), "agents/aidata.hermes", "hash stripped");
eq(safeLoginNext("settings/theme"), "settings/theme", "settings kept");
eq(safeLoginNext("activity"), "activity", "activity kept");
eq(safeLoginNext("network"), "network", "network kept");
eq(safeLoginNext("users"), "users", "users kept");
eq(safeLoginNext("agents/lab.echo"), "agents/lab.echo", "agent detail kept");
eq(safeLoginNext("", true), "", "allow empty");
eq(safeLoginNext("login", true), "", "login empty when allowed");
eq(safeLoginNext("https://x", true), "", "bad next empty when allowed");

eq(loginHash(""), "#/login", "plain login");
eq(loginHash("explore"), "#/login", "explore is default");
eq(loginHash("publish/hub"), "#/login?next=publish%2Fhub", "next encoded");
eq(loginHash("https://x"), "#/login", "bad next dropped");
eq(loginHash("activity"), "#/login?next=activity", "activity next");
eq(loginHash("explore?q=hermes"), "#/login?next=explore%3Fq%3Dhermes", "search next");

eq(intendedRoutePath(r(["explore"])), "", "default explore omitted");
eq(intendedRoutePath(r(["explore"], "q=hermes")), "explore?q=hermes", "search kept");
eq(intendedRoutePath(r(["login"])), "", "login omitted");
eq(intendedRoutePath(r(["login"], "next=activity")), "", "login query omitted");
eq(intendedRoutePath(r(["publish", "hub"])), "publish/hub", "publish path");
eq(intendedRoutePath(r(["activity"], "kind=ticket")), "activity?kind=ticket", "activity query");
eq(intendedRoutePath(r(["settings", "theme"])), "settings/theme", "settings path");
eq(intendedRoutePath(r(["agents", "aidata.hermes"])), "agents/aidata.hermes", "agent path");

eq(gateHash(["explore"]), "#/login", "qa 1.1 explore");
eq(gateHash(["explore"], "q=hermes"), "#/login?next=explore%3Fq%3Dhermes", "search gate");
eq(gateHash(["activity"]), "#/login?next=activity", "qa 1.9 activity");
eq(gateHash(["publish", "hub"]), "#/login?next=publish%2Fhub", "qa 1.10 publish");
eq(gateHash(["login"]), "#/login", "already login");

eq(afterLoginDest(""), "#/explore", "login default dest");
eq(afterLoginDest(null), "#/explore", "login null dest");
eq(afterLoginDest("publish/hub"), "#/publish/hub", "login resume publish");
eq(afterLoginDest("activity"), "#/activity", "login resume activity");
eq(afterLoginDest("https://evil"), "#/explore", "login bad dest");
eq(afterLoginDest("login"), "#/explore", "login cannot resume login");

eq(loginErrorText("invalid username or password"), "用户名或密码错误", "wrong password");
eq(loginErrorText("session expired"), "请重新登录", "expired");
eq(loginErrorText("hub login required"), "请重新登录", "hub required");
eq(loginErrorText(""), "连接失败", "empty error");
eq(loginErrorText(null), "连接失败", "null error");
eq(loginErrorText("JSON 无法解析"), "JSON 无法解析", "passthrough");

eq(roleLabel("admin"), "管理员", "admin label");
eq(roleLabel("developer"), "开发者", "developer label");
eq(roleLabel("agent"), "agent", "unknown role");
eq(roleLabel(""), "未知", "empty role");

eq(withMotion("reduce", false), true, "pref reduce");
eq(withMotion("ok", true), false, "pref keep motion");
eq(withMotion("system", true), true, "system follow reduce");
eq(withMotion("system", false), false, "system follow motion");
eq(withMotion("", true), true, "missing attr follows system");

console.log(JSON.stringify({ ok: true }));
"""
    path = tmp_path / "hub_login_logic.js"
    path.write_text(extracted + "\n" + harness, encoding="utf-8")
    proc = subprocess.run(
        [_node_bin(), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        pytest.fail(proc.stderr or proc.stdout or "node 登录路由测试失败")
    return json.loads(proc.stdout)


def test_login_route_logic_executes_from_app_js(tmp_path):
    result = _run_login_logic(tmp_path)
    assert result["ok"] is True


def test_login_hash_wired():
    js = APP_JS.read_text(encoding="utf-8")
    assert "function safeLoginNext" in js
    assert "function loginHash" in js
    assert "function goLogin" in js
    assert "function loginErrorText" in js
    assert "function motionReduced" in js
    assert 'location.hash = "#/login"' in js
    assert 'if (r.parts[0] !== "login")' in js
    assert 'if (r.parts[0] === "login")' in js
    assert 'route().query.get("next")' in js
    assert 'const dest = "#/" + safeLoginNext(route().query.get("next"))' in js
    assert "goLogin(e.message, intendedRoutePath(route()))" in js
    assert "goLogin(\"\", intendedRoutePath(r))" in js
    assert "clearSession()" in js
    assert 'sessionStorage.setItem(TOKEN_KEY' in js
    assert 'sessionStorage.removeItem(TOKEN_KEY)' in js
    assert 'sessionStorage.removeItem(LEGACY_TOKEN_KEY)' in js


def test_login_page_markup_and_css_contract():
    js = APP_JS.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")

    assert 'class="login-page"' in js
    assert 'class="login-visual"' in js
    assert 'class="login-gather"' in js
    assert 'id="login-bits"' in js
    assert 'id="agent-card-btn"' in js
    assert 'id="login-dialog"' in js
    assert 'id="login-form"' in js
    assert 'id="login-username"' in js
    assert 'id="login-password"' in js
    assert 'id="login-err"' in js
    assert 'id="role-help"' in js
    assert 'id="role-help-btn"' in js
    assert "权限说明" in js
    assert 'data-account="admin"' in js
    assert 'data-account="developer"' in js
    assert 'required placeholder="请输入用户名"' in js
    assert 'type="password"' in js
    assert "autocomplete=\"current-password\" required" in js
    assert "用户名或密码错误" in js
    assert "请重新登录" in js
    assert "playAgentCardGather" in js
    assert "6800" in js
    assert "count = reduce ? 0 : 128" in js
    assert 'agent-card-title">Agent</span>' in js
    assert 'agent-card-title">Card</span>' in js
    assert 'agent-card-kicker">名片' not in js
    assert 'class="login-brand-name">SUNNY<' not in js
    assert 'class="login-foot">SUNNY · Agent Hub · <a href="/help/">文档门户</a></footer>' in js
    assert "/assets/login-handshake.png" in js
    assert "/api/v1/auth/login" in js
    assert "/api/v1/auth/me" in js
    assert 'id: "btn-logout"' in js
    assert "function roleLabel" in js
    assert "function setGateMode" in js
    assert 'classList.toggle("is-login"' in js

    assert 'id="account"' in html
    assert 'src="/assets/sunny-logo.png' in html
    assert "/assets/app.js" in html

    assert "body.is-login" in css
    assert "body.is-login .topbar { display: none; }" in css
    assert ".login-page" in css
    assert ".login-visual" in css
    assert ".login-gather" in css
    assert ".agent-card-btn" in css
    assert ".login-dialog" in css
    assert ".role-help" in css
    assert ".login-err.is-on" in css
    assert "75vw" in css
    assert "16 / 9" in css
    assert "html[data-motion=\"reduce\"] .login-bit" in css
    assert "box-shadow: none" in css


def test_login_page_still_served(client):
    index = client.get("/")
    js = client.get("/assets/app.js")
    css = client.get("/assets/app.css")
    handshake = client.get("/assets/login-handshake.png")
    logo = client.get("/assets/sunny-logo.png")
    assert index.status_code == 200
    assert js.status_code == 200
    assert css.status_code == 200
    assert handshake.status_code == 200
    assert handshake.headers.get("content-type", "").startswith("image/")
    assert logo.status_code == 200
    assert "function loginView" in js.text
    assert "function goLogin" in js.text
    assert "/api/v1/auth/login" in js.text


def _login(client: TestClient, username: str, password: str):
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def test_login_admin_and_developer_success(client):
    admin = _login(client, "admin", "admin-test")
    assert "token" in admin and admin["token"]
    assert admin["user"]["username"] == "admin"
    assert admin["user"]["role"] == "admin"
    assert admin["user"]["kind"] == "admin"
    assert admin["user"]["permissions"]["manage_users"] is True
    assert admin["user"]["permissions"]["view_activity"] is True
    assert admin["user"]["permissions"]["view_graph"] is True
    assert admin["user"]["permissions"]["publish"] is True
    assert "password" not in admin
    assert "password" not in admin["user"]
    assert "password_hash" not in admin["user"]
    payload = security.verify_session("ticket-test", admin["token"])
    assert payload is not None
    assert payload["typ"] == "session"
    assert payload["kind"] == "admin"
    assert payload["username"] == "admin"

    developer = _login(client, "developer", "dev-test-password")
    assert developer["user"]["role"] == "developer"
    assert developer["user"]["permissions"]["view_cards"] is True
    assert developer["user"]["permissions"]["publish"] is True
    assert developer["user"]["permissions"]["manage_users"] is False
    assert developer["user"]["permissions"]["view_activity"] is False
    assert developer["user"]["permissions"]["view_graph"] is False
    assert developer["user"]["permissions"]["manage_all_agents"] is False


def test_login_rejects_bad_credentials(client):
    wrong = client.post(
        "/api/v1/auth/login",
        json={"username": "developer", "password": "wrong-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "invalid username or password"

    missing = client.post(
        "/api/v1/auth/login",
        json={"username": "no-such-user", "password": "dev-test-password"},
    )
    assert missing.status_code == 401
    assert missing.json()["detail"] == "invalid username or password"

    empty = client.post("/api/v1/auth/login", json={"username": "", "password": ""})
    assert empty.status_code == 401
    assert empty.json()["detail"] == "invalid username or password"

    spaced = client.post(
        "/api/v1/auth/login",
        json={"username": "Admin", "password": "admin-test"},
    )
    assert spaced.status_code == 401

    incomplete = client.post("/api/v1/auth/login", json={"username": "admin"})
    assert incomplete.status_code == 422


def test_login_trims_username(client):
    body = _login(client, "  admin  ", "admin-test")
    assert body["user"]["username"] == "admin"


def test_login_session_me_and_catalog_gate(client):
    anonymous_me = client.get("/api/v1/auth/me")
    assert anonymous_me.status_code == 401
    assert anonymous_me.json()["detail"] == "hub login required"

    anonymous_catalog = client.get("/api/v1/agents")
    assert anonymous_catalog.status_code == 401

    login = _login(client, "developer", "dev-test-password")
    headers = {"Authorization": "Bearer " + login["token"]}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "developer"
    assert me.json()["role"] == "developer"
    catalog = client.get("/api/v1/agents", headers=headers)
    assert catalog.status_code == 200
    assert "items" in catalog.json()


def test_login_session_is_not_a_call_ticket(client):
    from fastapi import HTTPException

    login = _login(client, "admin", "admin-test")
    with pytest.raises(HTTPException) as exc:
        security.verify_ticket("ticket-test", login["token"])
    assert exc.value.status_code == 401
    assert exc.value.detail == "not a call ticket"

    verify = client.post(
        "/api/v1/tickets/verify",
        headers={"Authorization": "Bearer " + login["token"]},
        json={"ticket": login["token"]},
    )
    assert verify.status_code == 401
    assert verify.json()["detail"] == "not a call ticket"


def test_login_developer_cannot_issue_tickets(client):
    login = _login(client, "developer", "dev-test-password")
    denied = client.post(
        "/api/v1/tickets",
        headers={"Authorization": "Bearer " + login["token"]},
        json={"callee_id": "aidata.hermes", "skill_id": "collect.strategy.query", "caller_id": "lab.inspector"},
    )
    assert denied.status_code == 403
    assert "developers cannot" in denied.json()["detail"]
