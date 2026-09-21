from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP_JS = WEB / "assets" / "app.js"
APP_CSS = WEB / "assets" / "app.css"
INDEX = WEB / "index.html"


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.db_path = tmp_path / "hub-settings.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _extract_span(src: str, start_token: str, end_fn: str) -> str:
    start = src.find(start_token)
    if start < 0:
        raise AssertionError("app.js 缺少 " + start_token)
    token = "function " + end_fn + "("
    fn_start = src.find(token, start)
    if fn_start < 0:
        raise AssertionError("app.js 缺少 function " + end_fn)
    brace = src.find("{", fn_start)
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
    raise AssertionError("function " + end_fn + " 花括号不配对")


def _run_settings_logic(tmp_path: Path):
    node = shutil.which("node")
    if not node:
        pytest.fail("需要本机 node 才能执行设置页逻辑测试")
    src = APP_JS.read_text(encoding="utf-8")
    extracted = _extract_span(src, "const PREFS_KEY", "writePrefs")
    harness = r"""
function fail(msg) { throw new Error(msg); }
function eq(actual, expected, msg) {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) fail((msg || "assert") + " expected " + right + " got " + left);
}
const store = {};
global.localStorage = {
  getItem: function (key) { return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null; },
  setItem: function (key, value) { store[key] = String(value); },
  removeItem: function (key) { delete store[key]; }
};
const attrs = {};
global.document = {
  documentElement: {
    setAttribute: function (key, value) { attrs[key] = value; },
    getAttribute: function (key) { return attrs[key]; }
  }
};

eq(pickEnum("swiss", PREF_ENUMS.theme, "light"), "swiss", "known theme");
eq(pickEnum("hacker", PREF_ENUMS.theme, "light"), "light", "unknown theme");
eq(pickEnum("reduce", PREF_ENUMS.motion, "system"), "reduce", "known motion");

const empty = readPrefs();
eq(empty.theme, "light", "default theme");
eq(empty.font, "inter", "default font");
eq(empty.mono, "jetbrains", "default mono");
eq(empty.typeSize, "default", "default type");
eq(empty.density, "default", "default density");
eq(empty.motion, "system", "default motion");

localStorage.setItem(PREFS_KEY, JSON.stringify({
  theme: "tactical",
  font: "noto",
  motion: "nope",
  extra: "drop-me"
}));
const loaded = readPrefs();
eq(loaded.theme, "tactical", "keep tactical");
eq(loaded.font, "noto", "keep noto");
eq(loaded.motion, "system", "bad motion fallback");
if (loaded.extra) fail("unknown pref leaked");

const written = writePrefs({ theme: "shop", motion: "reduce", themeX: "no" });
eq(written.theme, "shop", "write shop");
eq(written.motion, "reduce", "write reduce");
eq(attrs["data-theme"], "shop", "attr theme");
eq(attrs["data-motion"], "reduce", "attr motion");
eq(attrs["data-font"], "noto", "attr font kept");
const saved = JSON.parse(localStorage.getItem(PREFS_KEY));
eq(saved.theme, "shop", "persist theme");
if (saved.themeX) fail("invalid patch persisted");

writePrefs({ theme: "hacker" });
eq(readPrefs().theme, "light", "invalid write falls back");
eq(attrs["data-theme"], "light", "invalid attr falls back");

localStorage.removeItem(PREFS_KEY);
const reset = readPrefs();
eq(reset.theme, "light", "reset theme");
applyPrefs(reset);
eq(attrs["data-theme"], "light", "reset attr");

console.log(JSON.stringify({ ok: true, themes: PREF_ENUMS.theme }));
"""
    path = tmp_path / "hub_settings_logic.js"
    path.write_text(extracted + "\n" + harness, encoding="utf-8")
    proc = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        pytest.fail(proc.stderr or proc.stdout or "node 设置页逻辑测试失败")
    return json.loads(proc.stdout)


def test_settings_prefs_logic_executes_from_app_js(tmp_path):
    result = _run_settings_logic(tmp_path)
    assert result["ok"] is True
    assert result["themes"] == ["light", "dark", "swiss", "tactical", "shop"]


def test_settings_page_contract():
    js = APP_JS.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")

    assert 'function settingsView' in js
    assert 'function readPrefs' in js
    assert 'function writePrefs' in js
    assert 'function applyPrefs' in js
    assert 'function pickEnum' in js
    assert 'sunny.hub.prefs' in js
    assert '["theme", "type", "display"].indexOf(section)' in js
    assert '<h1>系统设置</h1>' in js
    assert "主题设置" in js
    assert "界面字体" in js
    assert "等宽字体" in js
    assert "字号" in js
    assert "密度" in js
    assert "动效" in js
    assert "减弱动效" in js
    assert "跟随系统" in js
    assert "保持动效" in js
    assert 'id: "btn-prefs-reset"' in js
    assert "恢复默认" in js
    assert 'href="/help/"' in js
    assert "不进顶栏" in js
    assert "不进账号、不影响出票" in js
    for theme in ("light", "dark", "swiss", "tactical", "shop"):
        assert 'id: "' + theme + '"' in js
    for theme in ("dark", "swiss", "tactical", "shop"):
        assert 'html[data-theme="' + theme + '"]' in css
    assert ":root {" in css
    assert 'href="#/settings/theme"' in html
    assert ">系统设置</a>" in html
    assert "sunny.hub.prefs" in html
    assert ".theme-card" in css
    assert ".settings-nav" in css
    assert 'html[data-motion="reduce"]' in css


def test_settings_assets_served(client):
    js = client.get("/assets/app.js")
    css = client.get("/assets/app.css")
    index = client.get("/")
    assert js.status_code == 200
    assert css.status_code == 200
    assert index.status_code == 200
    assert "function settingsView" in js.text
    assert "function writePrefs" in js.text
    assert "SUNNY · Agent Hub" in index.text
    assert 'href="#/settings/theme"' in index.text
