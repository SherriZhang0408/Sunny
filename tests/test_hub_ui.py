from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "hub-ui.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def test_hub_index_and_spa_fallback(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers.get("content-type", "")
    html = index.text
    assert 'lang="zh-CN"' in html
    assert "SUNNY · Agent Hub" in html
    assert "<title>SUNNY · Agent Hub</title>" in html
    assert 'id="global-search"' in html
    assert 'href="#/explore"' in html
    assert 'href="#/publish"' in html
    assert "/assets/app.css" in html
    assert "/assets/app.js" in html

    spa = client.get("/agents/aidata.hermes")
    assert spa.status_code == 200
    assert "SUNNY · Agent Hub" in spa.text

    missing_api = client.get("/api/v1/not-a-route")
    assert missing_api.status_code == 404


def test_hub_assets_served(client):
    css = client.get("/assets/app.css")
    assert css.status_code == 200
    js = client.get("/assets/app.js")
    assert js.status_code == 200
    assert "function controlBtn" in js.text
    handshake = client.get("/assets/login-handshake.png")
    assert handshake.status_code == 200
    assert handshake.headers.get("content-type", "").startswith("image/")


def test_hub_control_taxonomy_and_colors():
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")

    for token in ("--hub:", "--self:", "--danger:", "--stale:", "--ok:", "--docker:", "--selected:", "--brand-green:", "--brand-silver:"):
        assert token in css
    for selector in (".btn {", ".btn-primary {", ".btn-danger {", ".btn-warning {", ".btn-success {", ".btn-ghost {", ".seg {", ".seg-item {", ".tabs .tab {", ".badge,", ".tag {"):
        assert selector in css
    assert ".seg-item.active {" in css
    assert "background: var(--selected)" in css
    assert ".seg-item.active.source-hub" not in css
    assert ".seg-item.active.source-self" not in css
    assert ".topnav a.active { background: var(--selected)" in css

    assert 'classes = ["btn", "btn-" + variant]' in js
    assert "function sourceSeg" in js
    assert "function approvalSelect" in js
    assert 'id="approval-filter"' in js
    assert "filter-bar" in js
    assert "filter-select" in js
    assert "hero-points" in js
    assert "登记注册" in js
    assert "要用别的智能体，先拿到它的名片" in js
    assert 'filter-label">来源' not in js
    assert "待审批" in js
    assert "已通过" in js
    assert '["approved", "已通过"]' in js
    assert "需审批后可见" in js
    assert 'id: "btn-approve"' in js
    assert 'id: "btn-deprecate"' in js
    assert "已弃用" in js
    assert "/api/v1/agents/" in js and "approve" in js
    assert 'class="seg"' in js
    assert "data-source" in js
    assert "function agentActions" in js
    assert "function probeHtml" in js
    assert "unreachable: \"不可达\"" in js
    assert 'id: "btn-probe"' in js
    assert "探活名片" in js
    assert 'variant: "primary"' in js
    assert 'variant: "danger"' in js
    assert 'variant: "warning"' in js
    assert 'variant: "success"' in js
    assert "params.set(\"enrollment_source\", source)" in js
    assert "params.set(\"runtime_status\", status)" in js
    assert "params.set(\"q\", q)" in js
    assert "function kindSeg" in js
    assert "function activityHash" in js
    assert "data-kind" in js
    assert "id=\"trace-filter\"" in js
    assert "按 trace_id 对账" in js


def test_hub_nav_permissions_wired():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'data-nav="network"' in (WEB / "index.html").read_text(encoding="utf-8")
    assert 'can("view_graph")' in js or "view_graph" in js
    assert 'can("view_activity")' in js or "view_activity" in js
    assert 'can("manage_users")' in js or "manage_users" in js
    assert "loginView" in js
    assert "function goLogin" in js
    assert 'location.hash = "#/login"' in js
    assert "#/login" in js
    assert 'class="login-page"' in js
    assert 'class="login-avatar"' in js
    assert 'class="login-visual"' in js
    assert "/assets/login-handshake.png" in js
    css_text = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert "border: 0" in css_text
    assert ".login-visual" in css_text
    assert ".login-gather" in css_text
    assert ".agent-card-btn" in css_text
    assert "position: fixed;" in css_text
    assert "75vw" in css_text
    assert "16 / 9" in css_text
    assert "justify-content: center;" in css_text
    assert "opacity: var(--login-visual-opacity)" in css_text
    assert "box-shadow: none" in css_text
    assert 'src="/assets/sunny-logo.png' in (WEB / "index.html").read_text(encoding="utf-8")
    assert "<h1>智能体 · 名片</h1>" in js
    assert "像人类交换名片" in js
    assert 'class="login-brand-name">SUNNY<' not in js
    assert 'class="login-foot">SUNNY · Agent Hub<' in js
    assert 'id="agent-card-btn"' in js
    assert 'id="login-dialog"' in js
    assert 'id="login-bits"' in js
    assert "playAgentCardGather" in js
    assert "点击打开登录" in js
    assert 'agent-card-kicker">名片' not in js
    assert 'id="role-help"' in js
    assert "loginErrorText" in js
    assert "用户名或密码错误" in js
    assert ".login-page" in (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert "exploreView" in js
    assert "publishView" in js
    assert "function publishPages" in js
    assert "function applyPublishTab" in js
    assert "function bindPublishPager" in js
    assert 'id="publish-pager"' in js
    assert 'id="publish-track"' in js
    assert 'id="publish-shell"' in js
    assert "#/publish/" in js
    assert 'id: "hub"' in js
    assert 'id: "pull"' in js
    assert 'id: "join"' in js
    assert 'id: "self"' not in js
    assert "data-tab=\"" in js
    assert "点上方分类" not in js
    assert "底部圆点" not in js
    assert "左右滑动" not in js
    assert "从 URL 拉取名片" in js
    assert "/api/v1/agents/pull" in js
    assert '<select id="src">' not in js
    assert "<label>登记方式</label>" not in js
    assert "完整名片" in js
    assert "/extended" in js
    assert "公开名片" in js
    assert "restricted" in js
    assert 'id: "btn-refresh"' in js
    assert "刷新名片" in js
    assert "usersView" in js
    assert 'data-nav="settings"' in (WEB / "index.html").read_text(encoding="utf-8")
    assert ">账号管理</a>" in (WEB / "index.html").read_text(encoding="utf-8")
    assert ">系统设置</a>" in (WEB / "index.html").read_text(encoding="utf-8")
    assert ">账号</a>" not in (WEB / "index.html").read_text(encoding="utf-8")
    assert ">设置</a>" not in (WEB / "index.html").read_text(encoding="utf-8")
    assert '<h1>账号管理</h1>' in js
    assert '<h1>系统设置</h1>' in js
    assert "settingsView" in js
    assert "sunny.hub.prefs" in js
    assert 'id: "light"' in js
    assert 'id: "dark"' in js
    assert 'id: "swiss"' in js
    assert 'id: "tactical"' in js
    assert 'id: "shop"' in js
    assert "writePrefs" in js
    assert "主题设置" in js
    assert "界面字体" in js
    assert "密度" in js
    assert "开发者不能查看调用关系。" in js
    assert "开发者不能查看全局活动动态。" in js
    assert "只有管理员可以管理账号。" in js
    assert ".badge.approved" in (WEB / "assets" / "app.css").read_text(encoding="utf-8")


def test_explore_and_activity_logic_executes_from_app_js(tmp_path):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.fail("需要本机 node 才能执行浏览/活动页逻辑测试")
    src = (WEB / "assets" / "app.js").read_text(encoding="utf-8")

    def extract_fn(name: str) -> str:
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

    def extract_const(name: str) -> str:
        token = "const " + name + " ="
        start = src.find(token)
        if start < 0:
            raise AssertionError("app.js 缺少 const " + name)
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
        raise AssertionError("const " + name + " 花括号不配对")

    script = "\n".join(
        [
            extract_const("CHIP_LABELS"),
            extract_fn("chipLabel"),
            extract_fn("approvalSelect"),
            extract_fn("activityHash"),
            extract_fn("sourceSeg"),
            r"""
function fail(msg) { throw new Error(msg); }
function eq(actual, expected, msg) {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) fail((msg || "assert") + " expected " + right + " got " + left);
}
const options = approvalSelect("approved");
if (options.indexOf('value="approved"') < 0) fail("approved value");
if (options.indexOf("已通过") < 0) fail("approved label");
if (options.indexOf("全部审批") < 0) fail("all approval");
if (options.indexOf("待审批") < 0) fail("pending");
if (options.indexOf("已拒绝") < 0) fail("rejected");
if (options.indexOf('value="approved" selected') < 0) fail("approved selected");
eq(chipLabel("source", "hub"), "管理台填入", "hub source");
eq(chipLabel("source", "self"), "主动注册", "self source");
eq(chipLabel("approval", "approved"), "已通过", "approved chip");
eq(chipLabel("approval", "pending"), "待审批", "pending chip");
eq(activityHash("", "", ""), "#/activity", "plain activity");
eq(activityHash("ticket", "hub-qa-1", ""), "#/activity?kind=ticket&trace_id=hub-qa-1", "trace hash");
eq(activityHash("search", "", "hermes"), "#/activity?kind=search&q=hermes", "search hash");
const seg = sourceSeg("hub");
if (seg.indexOf("全部来源") < 0) fail("all sources");
if (seg.indexOf("管理台填入") < 0) fail("hub label");
if (seg.indexOf("主动注册") < 0) fail("self label");
if (seg.indexOf('data-source="hub"') < 0) fail("hub data");
console.log(JSON.stringify({ ok: true }));
""",
        ]
    )
    path = tmp_path / "hub_explore_logic.js"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        pytest.fail(proc.stderr or proc.stdout or "node 浏览/活动页逻辑测试失败")
    assert json.loads(proc.stdout)["ok"] is True


def test_hub_theme_tokens():
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert ":root {" in css
    for theme in ("dark", "swiss", "tactical", "shop"):
        assert 'html[data-theme="' + theme + '"]' in css
    assert 'html[data-font="noto"]' in css
    assert 'html[data-type-size="comfortable"]' in css
    assert 'html[data-density="compact"]' in css
    assert "sunny.hub.prefs" in html
    assert ".theme-card" in css
    assert ".settings-nav" in css
    assert ".publish-pager" in css
    assert ".publish-track" in css
    assert ".publish-page" in css
    assert ".publish-dots" not in css
    assert ".publish-hint" not in css
