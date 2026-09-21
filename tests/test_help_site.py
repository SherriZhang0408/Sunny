from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse

from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"
WEB = ROOT / "web"
PAGES = ("index.html", "briefing.html", "engineering.html", "api.html")
NAV = ("文档门户", "项目介绍", "工程说明", "API 参考")


class _PageLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: List[str] = []
        self.srcs: List[str] = []
        self.ids: Set[str] = set()
        self.text_chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = dict(attrs)
        if data.get("id"):
            self.ids.add(data["id"])
        if tag == "a" and data.get("href"):
            self.hrefs.append(data["href"])
        if tag in ("script", "link", "img") and data.get("src"):
            self.srcs.append(data["src"])
        if tag == "link" and data.get("href"):
            self.hrefs.append(data["href"])

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text_chunks.append(data)


def _parse(html: str) -> _PageLinks:
    parser = _PageLinks()
    parser.feed(html)
    return parser


def _help_client(tmp_path) -> TestClient:
    settings = Settings()
    settings.db_path = tmp_path / "help-site.db"
    settings.admin_token = "admin-test"
    settings.developer_password = "dev-test-password"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _local_targets(base: str, refs: List[str]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    seen = set()
    for raw in refs:
        if raw.startswith("#") or raw.startswith("data:") or raw.startswith("mailto:"):
            continue
        if raw.startswith("http://") or raw.startswith("https://"):
            continue
        joined = urljoin("http://help.local/help/" + base, raw)
        path = urlparse(joined).path
        if path in seen:
            continue
        seen.add(path)
        out.append((raw, path))
    return out


def test_help_portal_is_public(tmp_path):
    tc = _help_client(tmp_path)
    redirect = tc.get("/help", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/help/"

    page = tc.get("/help/")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert "charset=utf-8" in page.headers.get("content-type", "").lower()
    assert "文档门户" in page.text
    assert "项目介绍" in page.text
    assert "项目汇报" not in page.text
    assert 'data-nav="explore"' not in page.text
    assert "SUNNY_ENROLL_TOKEN" not in page.text


def test_help_pages_assets_and_anchors(tmp_path):
    tc = _help_client(tmp_path)
    fetched: Dict[str, str] = {}
    for name in PAGES:
        res = tc.get("/help/" + name)
        assert res.status_code == 200, name
        assert "charset=utf-8" in res.headers.get("content-type", "").lower()
        fetched[name] = res.text
        parsed = _parse(res.text)
        assert "项目汇报" not in res.text
        for label in NAV:
            assert label in res.text
        missing = [
            href
            for href in parsed.hrefs
            if href.startswith("#") and href != "#" and href[1:] not in parsed.ids
        ]
        assert not missing, name + " 缺锚点 " + ", ".join(missing)

        for raw, path in _local_targets(name, parsed.hrefs + parsed.srcs):
            if path.startswith("/help/../") or "/specs/" in path:
                raise AssertionError(name + " 链出文档站: " + raw)
            if not path.startswith("/help/"):
                continue
            hit = tc.get(path)
            assert hit.status_code == 200, name + " -> " + raw + " => " + path

    css = tc.get("/help/assets/site.css")
    js = tc.get("/help/assets/site.js")
    assert css.status_code == 200
    assert "text/css" in css.headers.get("content-type", "")
    assert js.status_code == 200
    assert "javascript" in js.headers.get("content-type", "")
    assert "data-print" in js.text
    assert "IntersectionObserver" in js.text
    assert fetched["briefing.html"].count('id="') >= 9
    assert 'data-print' in fetched["briefing.html"]
    assert SITE.joinpath("index.html").is_file()


def test_help_does_not_escape_or_steal_hub(tmp_path):
    tc = _help_client(tmp_path)
    hub_js = tc.get("/assets/app.js")
    hub_css = tc.get("/assets/app.css")
    spa = tc.get("/not-a-hub-page")
    missing = tc.get("/help/missing-page.html")
    specs = tc.get("/specs/adapter.md")
    traversal = tc.get("/help/%2e%2e/%2e%2e/README.md")
    nested = tc.get("/help/assets/%2e%2e/%2e%2e/README.md")

    assert hub_js.status_code == 200
    assert "function settingsView" in hub_js.text
    assert hub_css.status_code == 200
    assert spa.status_code == 200
    assert "SUNNY · Agent Hub" in spa.text
    assert missing.status_code == 404
    assert traversal.status_code == 404
    assert nested.status_code == 404
    assert "# Adapter" not in specs.text
    assert "deck.js" not in (SITE / "index.html").read_text(encoding="utf-8")
    for name in PAGES:
        html = (SITE / name).read_text(encoding="utf-8")
        assert "deck.js" not in html
        assert not re.search(r'href=["\']\.\./', html), name + " 仍有跳出 /help/ 的相对链接"


def test_help_same_for_anonymous_and_session(tmp_path):
    tc = _help_client(tmp_path)
    anon = tc.get("/help/briefing.html")
    login = tc.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-test"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    authed = tc.get("/help/briefing.html", headers={"Authorization": "Bearer " + token})
    assert anon.status_code == 200
    assert authed.status_code == 200
    assert anon.text == authed.text


def test_hub_entry_points_point_at_help():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'class="login-foot">SUNNY · Agent Hub · <a href="/help/">文档门户</a></footer>' in js
    assert 'href="/help/engineering.html" target="_blank" rel="noopener"' in js
    assert 'href="/help/api.html" target="_blank" rel="noopener"' in js
    assert 'href="/help/" target="_blank" rel="noopener">文档门户</a>，不进顶栏' in js
    assert 'data-nav="help"' not in html
    assert ">文档门户</a>" not in html
    assert "/assets/app.js?v=49" in html
    assert "/assets/app.css?v=55" in html
    assert ".login-foot a" in css
    assert "function settingsView" in js
    display = js.split('} else {', 1)[1]
    theme = js.split('if (tab === "theme")', 1)[1].split("} else if", 1)[0]
    assert "不进顶栏" in display
    assert "不进顶栏" not in theme
