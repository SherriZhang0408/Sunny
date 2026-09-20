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
    assert "SUNNY Hub" in html
    assert 'id="global-search"' in html
    assert 'href="#/explore"' in html
    assert 'href="#/publish"' in html
    assert "/assets/app.css" in html
    assert "/assets/app.js" in html

    spa = client.get("/agents/aidata.hermes")
    assert spa.status_code == 200
    assert "SUNNY Hub" in spa.text

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
    assert 'class="login-foot">SUNNY Agent Hub<' in js
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
    assert "从 URL 拉取名片" in js
    assert "/api/v1/agents/pull" in js
    assert "完整名片" in js
    assert "/extended" in js
    assert "公开名片" in js
    assert "restricted" in js
    assert 'id: "btn-refresh"' in js
    assert "刷新名片" in js
    assert "usersView" in js
    assert 'data-nav="settings"' in (WEB / "index.html").read_text(encoding="utf-8")
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
