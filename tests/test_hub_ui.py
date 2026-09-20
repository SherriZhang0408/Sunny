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
    assert "function approvalSeg" in js
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
    assert "/assets/sunny-logo.png" in js
    assert 'class="login-brand-name">SUNNY<' in js
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
