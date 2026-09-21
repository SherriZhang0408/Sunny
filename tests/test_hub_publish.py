from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import httpx

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry.pull import USER_AGENT

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP_JS = WEB / "assets" / "app.js"
APP_CSS = WEB / "assets" / "app.css"
INDEX = WEB / "index.html"

LOGIC_FNS = (
    "publishPages",
    "resolvePublishTab",
    "discoveryOptions",
)


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "hub-publish.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    settings.pull_timeout_s = 0.5
    settings.public_url = "http://192.0.2.10:8088"
    return TestClient(create_app(settings))


def _card(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def _owned_card(agent_id: str, name: str, **sunny) -> dict:
    card = json.loads(json.dumps(_card("lab.inspector.sample.json")))
    card["name"] = name
    card["description"] = name + " 的说明"
    card["x-sunny"]["agent_id"] = agent_id
    card["x-sunny"].update(sunny)
    return card


def _login(client: TestClient, username: str, password: str):
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    body = res.json()
    return {"Authorization": "Bearer " + body["token"]}, body["user"]


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
        pytest.fail("需要本机 node 才能执行发布页逻辑测试")
    return path


def _run_publish_logic(tmp_path: Path):
    src = APP_JS.read_text(encoding="utf-8")
    extracted = "\n\n".join(_extract_js_function(src, name) for name in LOGIC_FNS)
    harness = r"""
function fail(msg) { throw new Error(msg); }
function eq(actual, expected, msg) {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) fail((msg || "assert") + " expected " + right + " got " + left);
}
const pages = publishPages();
eq(pages.map(function (p) { return p.id; }), ["hub", "pull", "join"], "publish pages");
eq(pages.map(function (p) { return p.label; }), ["主动登记", "网址同步", "发给智能体"], "publish labels");
eq(pages.some(function (p) { return p.id === "self"; }), false, "no enroll-token tab");

eq(resolvePublishTab("pull", pages), "pull", "resolve pull");
eq(resolvePublishTab("self", pages), "hub", "self hash fallback");
eq(resolvePublishTab("nope", pages), "hub", "unknown fallback");
eq(resolvePublishTab(undefined, pages), "hub", "empty fallback");
eq(resolvePublishTab("join", pages), "join", "join");

const keep = discoveryOptions(true);
const fresh = discoveryOptions(false);
if (keep.indexOf("沿用 Card") < 0) fail("pull keeps card discovery");
if (keep.indexOf("需审批后可见") < 0) fail("pull has approval");
if (fresh.indexOf("沿用 Card") >= 0) fail("hub must not keep card option");
if (fresh.indexOf("登记后对等可见（默认）") < 0) fail("hub default discovery");
if (fresh.indexOf("仅自己与管理员") < 0) fail("private option");

console.log(JSON.stringify({
  ok: true,
  pages: pages.map(function (p) { return p.id; })
}));
"""
    script = extracted + "\n" + harness
    path = tmp_path / "hub_publish_logic.js"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [_node_bin(), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        pytest.fail(proc.stderr or proc.stdout or "node 发布页逻辑测试失败")
    return json.loads(proc.stdout)


def test_publish_logic_executes_from_app_js(tmp_path):
    result = _run_publish_logic(tmp_path)
    assert result["ok"] is True
    assert result["pages"] == ["hub", "pull", "join"]


def test_card_json_placeholder_is_aidata_example(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.fail("需要本机 node 才能执行名片示例测试")
    src = APP_JS.read_text(encoding="utf-8")
    extracted = _extract_js_function(src, "cardJsonPlaceholder")
    script = extracted + r"""
const text = cardJsonPlaceholder();
const card = JSON.parse(text);
if (card.name !== "AI 数据智能体") throw new Error("name");
if (card["x-sunny"].agent_id !== "your.org.aidata") throw new Error("agent_id");
if (card["x-sunny"].agent_id === "aidata.hermes") throw new Error("must not reuse hermes id");
const ids = card.skills.map(function (s) { return s.id; });
if (JSON.stringify(ids) !== JSON.stringify(["collect.strategy.query", "collect.volume.query"])) {
  throw new Error("skills " + JSON.stringify(ids));
}
if (text.indexOf("ai_collect") < 0) throw new Error("volume skill");
console.log(JSON.stringify({ ok: true, skills: ids }));
"""
    path = tmp_path / "card_placeholder.js"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        pytest.fail(proc.stderr or proc.stdout or "node 名片示例测试失败")
    body = json.loads(proc.stdout)
    assert body["ok"] is True
    assert body["skills"] == ["collect.strategy.query", "collect.volume.query"]


def test_publish_helpers_wired_into_pager():
    js = APP_JS.read_text(encoding="utf-8")
    assert "function publishSwipe" not in js
    assert "function publishNextIndex" not in js
    assert "pointerdown" not in js
    assert "ArrowLeft" not in js
    assert "左右滑动" not in js
    assert "点上方分类" not in js
    assert "底部圆点" not in js
    assert "publish-hint" not in js
    assert "publish-dots" not in js
    assert 'label: "主动登记"' in js
    assert "自己填写" not in js
    assert 'label: "网址同步"' in js
    assert "从网址拉" not in js
    assert 'label: "发给智能体"' in js
    assert "代为登记" not in js
    assert "这页不登记" in js
    assert 'href="/help/engineering.html"' in js
    assert 'href="/help/api.html"' in js
    assert "导出说明（含令牌）" in js
    assert "publishView(r.parts[1])" in js
    assert "releasePublishGestures()" in js
    assert "enrollment_source: source" in js
    assert 'bindCardForm("pub"' in js
    assert 'bindCardForm("pub-self"' not in js
    assert 'id="pull-agent-id"' in js
    assert 'id: "export-join-token"' in js
    assert "X-Sunny-Enroll" not in js
    assert '<select id="src">' not in js


def test_publish_markup_and_css_contract():
    js = APP_JS.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    assert 'href="#/publish"' in html
    assert "/assets/app.js" in html
    assert 'id="publish-shell"' in js
    assert 'id="publish-pager"' in js
    assert 'id="publish-track"' in js
    assert 'role="tablist"' in js
    assert 'aria-label="发布方式"' in js
    assert 'id="pub"' in js
    assert 'id="pub-self"' not in js
    assert 'id="enroll"' not in js
    assert 'id="pull-form"' in js
    assert 'id="join-export"' in js
    assert "function cardJsonPlaceholder" in js
    assert "function applyCardJsonPlaceholder" in js
    assert "card-json-input" in js
    assert "your.org.aidata" in js
    assert "collect.strategy.query" in js
    assert "collect.volume.query" in js
    assert "JSON 无法解析" in js
    assert "请填写基址或 Card URL" in js
    assert ".publish-pager" in css
    assert ".publish-track" in css
    assert ".publish-page" in css
    assert ".publish-dots" not in css
    assert ".publish-hint" not in css
    assert "textarea.card-json-input::placeholder" in css
    assert "color: var(--text-muted)" in css
    assert "html[data-motion=\"reduce\"] .publish-pager" in css
    assert "html[data-motion=\"system\"] .publish-pager" in css


def test_publish_assets_served(client):
    js = client.get("/assets/app.js")
    css = client.get("/assets/app.css")
    index = client.get("/")
    assert js.status_code == 200
    assert css.status_code == 200
    assert index.status_code == 200
    body = js.text
    for name in LOGIC_FNS:
        assert "function " + name in body
    assert ".publish-pager" in css.text
    assert 'href="#/publish"' in index.text


def test_publish_hub_registers_as_current_user(client):
    headers, user = _login(client, "admin", "admin-test")
    res = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"card": _owned_card("qa.hub.session", "会话主动登记"), "enrollment_source": "hub"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["agent_id"] == "qa.hub.session"
    assert body["enrollment_source"] == "hub"
    assert body["created_by"] == user["user_id"]
    assert body["owner_username"] == "admin"
    assert body["agent_key"].startswith("sak_")
    listed = client.get("/api/v1/agents", headers=headers)
    assert "qa.hub.session" in {item["agent_id"] for item in listed.json()["items"]}


def test_publish_hub_approval_required_is_pending(client):
    headers, _ = _login(client, "developer", "dev-test-password")
    res = client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "card": _owned_card("qa.dev.pending", "开发者待审", discovery="approval_required"),
            "enrollment_source": "hub",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["approval_status"] == "pending"
    waiting = client.get("/api/v1/agents", headers=headers, params={"approval_status": "pending"})
    assert [item["agent_id"] for item in waiting.json()["items"]] == ["qa.dev.pending"]
    denied = client.post("/api/v1/agents/qa.dev.pending/approve", headers=headers)
    assert denied.status_code == 403


def test_publish_rejects_broken_card_json(client):
    headers, _ = _login(client, "admin", "admin-test")
    res = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"card": {"name": "不是名片"}, "enrollment_source": "hub"},
    )
    assert res.status_code == 400


def test_publish_join_export_session_matches_ui(client):
    public = client.get("/api/v1/join.md")
    assert public.status_code == 200
    assert "enroll-test" not in public.text
    join = client.get("/api/v1/join")
    assert join.status_code == 200
    assert join.json()["public_url"] == "http://192.0.2.10:8088"
    assert "0.0.0.0" not in join.json()["public_url"]
    assert "0.0.0.0" not in join.json()["card_skeleton"]["supportedInterfaces"][0]["url"]

    admin, _ = _login(client, "admin", "admin-test")
    secret = client.get("/api/v1/join.md", params={"include_token": "1"}, headers=admin)
    assert secret.status_code == 200
    assert "enroll-test" in secret.text

    developer, _ = _login(client, "developer", "dev-test-password")
    denied = client.get("/api/v1/join.md", params={"include_token": "1"}, headers=developer)
    assert denied.status_code == 403


def test_publish_pull_session_blocks_ssrf_and_empty_url(client):
    headers, _ = _login(client, "admin", "admin-test")
    empty = client.post("/api/v1/agents/pull", headers=headers, json={"url": ""})
    assert empty.status_code == 400
    file_url = client.post("/api/v1/agents/pull", headers=headers, json={"url": "file:///etc/passwd"})
    assert file_url.status_code == 400
    meta = client.post(
        "/api/v1/agents/pull",
        headers=headers,
        json={"url": "http://169.254.169.254/latest/meta-data"},
    )
    assert meta.status_code == 400


def test_publish_pull_developer_session_cannot_overlay_agent_id(client):
    card = _owned_card("lab.inspector", "巡检")
    del card["x-sunny"]["agent_id"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("user-agent") == USER_AGENT
        if request.url.path.endswith("/agent-card.json"):
            return httpx.Response(200, json=card)
        return httpx.Response(404)

    client.app.state.store.settings.http_transport = httpx.MockTransport(handler)
    headers, user = _login(client, "developer", "dev-test-password")
    denied = client.post(
        "/api/v1/agents/pull",
        headers=headers,
        json={"url": "http://sidecar.test:8091", "agent_id": "lab.hijack"},
    )
    assert denied.status_code == 403

    filled = _owned_card("qa.dev.pull", "开发者同步")

    def ok_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agent-card.json"):
            return httpx.Response(200, json=filled)
        return httpx.Response(404)

    client.app.state.store.settings.http_transport = httpx.MockTransport(ok_handler)
    pulled = client.post(
        "/api/v1/agents/pull",
        headers=headers,
        json={"url": "http://sidecar.test:8091"},
    )
    assert pulled.status_code == 200, pulled.text
    assert pulled.json()["agent_id"] == "qa.dev.pull"
    assert pulled.json()["created_by"] == user["user_id"]
    assert pulled.json()["owner_username"] == "developer"
    assert pulled.json()["card_source_url"].endswith("/agent-card.json")
