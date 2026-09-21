(function () {
  const TOKEN_KEY = "sunny.hub.token";
  const USER_KEY = "sunny.hub.user";
  const LEGACY_TOKEN_KEY = "sunny.admin.token";
  const PREFS_KEY = "sunny.hub.prefs";
  const PREF_DEFAULTS = {
    theme: "light",
    font: "inter",
    mono: "jetbrains",
    typeSize: "default",
    density: "default",
    motion: "system",
  };
  const THEMES = [
    { id: "light", name: "浅色", desc: "现用管理台，圆角与 Docker 蓝。" },
    { id: "dark", name: "深色", desc: "同一套控件，改成夜间底。" },
    { id: "swiss", name: "瑞士印刷", desc: "新闻纸、直角、航空红。" },
    { id: "tactical", name: "战术遥测", desc: "炭黑底、磷光字、红选中。" },
    { id: "shop", name: "机工告示", desc: "钢板、警戒条、ISO 状态色。" },
  ];
  const FONT_UI = [
    { id: "inter", name: "Inter" },
    { id: "noto", name: "Noto Sans SC" },
    { id: "plex", name: "IBM Plex Sans" },
    { id: "system", name: "系统字体" },
  ];
  const FONT_MONO = [
    { id: "jetbrains", name: "JetBrains Mono" },
    { id: "plex", name: "IBM Plex Mono" },
    { id: "system", name: "系统等宽" },
  ];
  const TYPE_SIZES = [
    { id: "compact", name: "紧凑" },
    { id: "default", name: "默认" },
    { id: "comfortable", name: "宽松" },
  ];
  const DENSITIES = [
    { id: "compact", name: "紧凑" },
    { id: "default", name: "默认" },
    { id: "comfortable", name: "宽松" },
  ];
  const MOTIONS = [
    { id: "system", name: "跟随系统" },
    { id: "reduce", name: "减弱动效" },
    { id: "ok", name: "保持动效" },
  ];
  const PREF_ENUMS = {
    theme: THEMES.map(function (item) { return item.id; }),
    font: FONT_UI.map(function (item) { return item.id; }),
    mono: FONT_MONO.map(function (item) { return item.id; }),
    typeSize: TYPE_SIZES.map(function (item) { return item.id; }),
    density: DENSITIES.map(function (item) { return item.id; }),
    motion: MOTIONS.map(function (item) { return item.id; }),
  };

  function pickEnum(value, allowed, fallback) {
    return allowed.indexOf(value) >= 0 ? value : fallback;
  }

  function readPrefs() {
    let raw = {};
    try { raw = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {}; } catch (e) { raw = {}; }
    const next = {};
    Object.keys(PREF_DEFAULTS).forEach(function (key) {
      next[key] = pickEnum(raw[key], PREF_ENUMS[key], PREF_DEFAULTS[key]);
    });
    return next;
  }

  function applyPrefs(prefs) {
    const p = prefs || readPrefs();
    const html = document.documentElement;
    html.setAttribute("data-theme", p.theme);
    html.setAttribute("data-font", p.font);
    html.setAttribute("data-mono", p.mono);
    html.setAttribute("data-type-size", p.typeSize);
    html.setAttribute("data-density", p.density);
    html.setAttribute("data-motion", p.motion);
  }

  function writePrefs(patch) {
    const merged = Object.assign(readPrefs(), patch || {});
    const next = {};
    Object.keys(PREF_DEFAULTS).forEach(function (key) {
      next[key] = pickEnum(merged[key], PREF_ENUMS[key], PREF_DEFAULTS[key]);
    });
    localStorage.setItem(PREFS_KEY, JSON.stringify(next));
    applyPrefs(next);
    return next;
  }

  applyPrefs(readPrefs());
  const main = document.getElementById("main");
  const modal = document.getElementById("modal");
  const account = document.getElementById("account");
  let currentUser = null;

  function token() {
    return sessionStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(LEGACY_TOKEN_KEY) || "";
  }

  function setSession(value, user) {
    sessionStorage.setItem(TOKEN_KEY, value || "");
    sessionStorage.removeItem(LEGACY_TOKEN_KEY);
    if (user) sessionStorage.setItem(USER_KEY, JSON.stringify(user));
    currentUser = user || null;
  }

  function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
    sessionStorage.removeItem(LEGACY_TOKEN_KEY);
    currentUser = null;
  }

  function can(perm) {
    return !!(currentUser && currentUser.permissions && currentUser.permissions[perm]);
  }

  function roleLabel(role) {
    if (role === "admin") return "管理员";
    if (role === "developer") return "开发者";
    return role || "未知";
  }

  function headers() {
    return {
      "Content-Type": "application/json",
      Authorization: "Bearer " + token(),
    };
  }

  async function api(path, options) {
    const res = await fetch(path, Object.assign({ headers: headers() }, options || {}));
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
    if (!res.ok) {
      const detail = (data && data.detail) || res.statusText;
      const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function route() {
    const raw = (location.hash || "#/explore").replace(/^#/, "");
    const [path, qs] = raw.split("?");
    const parts = path.split("/").filter(Boolean);
    const query = new URLSearchParams(qs || "");
    return { parts: parts.length ? parts : ["explore"], query };
  }

  function safeLoginNext(raw, allowEmpty) {
    let value = String(raw == null ? "" : raw).replace(/^#\/?/, "").trim();
    if (!value) return allowEmpty ? "" : "explore";
    if (/[:\\]/.test(value) || value.indexOf("//") >= 0) return allowEmpty ? "" : "explore";
    const head = (value.split("?")[0] || "").split("/").filter(Boolean)[0] || "";
    const allowed = {
      explore: true,
      network: true,
      activity: true,
      publish: true,
      users: true,
      settings: true,
      agents: true,
    };
    if (!allowed[head]) return allowEmpty ? "" : "explore";
    return value;
  }

  function loginHash(next) {
    let dest = safeLoginNext(next, true);
    if (dest === "explore") dest = "";
    return dest ? "#/login?next=" + encodeURIComponent(dest) : "#/login";
  }

  function intendedRoutePath(r) {
    const parts = (r && r.parts) || [];
    if (!parts.length || parts[0] === "login") return "";
    const qs = r.query && r.query.toString ? r.query.toString() : "";
    if (parts[0] === "explore" && parts.length === 1 && !qs) return "";
    return qs ? parts.join("/") + "?" + qs : parts.join("/");
  }

  function goLogin(error, next) {
    const want = loginHash(next);
    if ((location.hash || "") !== want) history.replaceState(null, "", want);
    syncNav();
    loginView(error);
  }

  function badge(kind, text) {
    return '<span class="badge ' + kind + '">' + escapeHtml(text) + "</span>";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // 动作按钮：primary=推进 · danger=销毁 · warning=停用 · success=恢复 · ghost=次要
  function controlBtn(label, options) {
    options = options || {};
    const variant = options.variant || "ghost";
    const type = options.type || "button";
    const classes = ["btn", "btn-" + variant];
    if (options.size) classes.push("btn-" + options.size);
    if (options.cls) classes.push(options.cls);
    const attrs = ['type="' + type + '"', 'class="' + classes.join(" ") + '"'];
    if (options.id) attrs.push('id="' + escapeHtml(options.id) + '"');
    if (options.extra) attrs.push(options.extra);
    return "<button " + attrs.join(" ") + ">" + label + "</button>";
  }

  function sourceSeg(source) {
    return (
      '<div class="seg" role="group" aria-label="按登记来源筛选">' +
      [
        ["", "全部来源", "source-all"],
        ["hub", chipLabel("source", "hub"), "source-hub"],
        ["self", chipLabel("source", "self"), "source-self"],
      ].map(function (pair) {
        const selected = source === pair[0];
        return (
          '<button type="button" class="seg-item ' + pair[2] + (selected ? " active" : "") +
          '" data-source="' + pair[0] + '" aria-pressed="' + (selected ? "true" : "false") + '">' +
          pair[1] + "</button>"
        );
      }).join("") +
      "</div>"
    );
  }

  function approvalSelect(approval) {
    return (
      '<label class="filter-select-wrap">' +
        '<span class="sr-only">按审批状态筛选</span>' +
        '<select class="filter-select" id="approval-filter" aria-label="按审批状态筛选">' +
        [
          ["", "全部审批"],
          ["pending", "待审批"],
          ["rejected", "已拒绝"],
          ["approved", "已通过"],
        ].map(function (pair) {
          const selected = approval === pair[0];
          return (
            '<option value="' + pair[0] + '"' + (selected ? " selected" : "") + ">" +
            pair[1] + "</option>"
          );
        }).join("") +
        "</select></label>"
    );
  }

  function pad2(value) {
    return (value < 10 ? "0" : "") + value;
  }

  function formatBeijing(value) {
    if (value == null || value === "" || value === "—") return "—";
    const date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    const beijing = new Date(date.getTime() + 8 * 60 * 60 * 1000);
    return (
      beijing.getUTCFullYear() + "-" +
      pad2(beijing.getUTCMonth() + 1) + "-" +
      pad2(beijing.getUTCDate()) + " " +
      pad2(beijing.getUTCHours()) + ":" +
      pad2(beijing.getUTCMinutes()) + ":" +
      pad2(beijing.getUTCSeconds())
    );
  }

  function datetimeHtml(value) {
    const text = formatBeijing(value);
    const raw = value == null ? "" : String(value);
    return '<time class="datetime"' + (raw && text !== "—" ? ' datetime="' + escapeHtml(raw) + '"' : "") + ">" +
      escapeHtml(text) + "</time>";
  }

  function probeHtml(probe) {
    if (!probe || probe.checked_at == null) return "尚未探活";
    const state = probe.ok ? "可达" : "不可达";
    const cat = !probe.ok && probe.category ? " · " + probe.category : "";
    const url = probe.url ? " · " + probe.url : "";
    const err = probe.ok || !probe.error ? "" : " · " + probe.error;
    return escapeHtml(state + cat + url + err) + " · " + datetimeHtml(probe.checked_at);
  }

  // 机器枚举值继续走 API；展示层统一中文，避免 Waiting / registered 中英混排
  const CHIP_LABELS = {
    status: {
      online: "在线",
      stale: "心跳过期",
      unknown: "等待中",
      waiting: "等待中",
      unreachable: "不可达",
      disabled: "已禁用",
    },
    source: {
      self: "主动注册",
      hub: "管理台填入",
    },
    lifecycle: {
      registered: "已登记",
      deprecated: "已弃用",
      disabled: "已禁用",
      draft: "草稿",
    },
    discovery: {
      registered_peers: "对等可见",
      private: "私有",
      approval_required: "待审批",
    },
    approval: {
      none: "无需审批",
      pending: "待审批",
      approved: "已通过",
      rejected: "已拒绝",
    },
  };

  const ACTION_LABELS = {
    create: "登记",
    register: "登记",
    update: "更新",
    disable: "停用",
    deprecate: "弃用",
    enable: "启用",
    heartbeat: "心跳",
    probe: "探活",
    pull: "拉取",
    refresh: "刷新",
    approve: "通过",
    reject: "拒绝",
    issue_key: "签发密钥",
    invoke: "调用上报",
    invocation: "调用上报",
    search: "搜索",
    ticket: "出票",
    issued: "出票",
    delete: "删除",
    patch: "更新",
  };

  const SUMMARY_LABELS = {
    "card updated": "名片已更新",
    "card pulled from well-known": "已从 URL 拉取名片",
    "card refreshed from well-known": "已从来源 URL 刷新名片",
    "registered via well-known pull": "Well-Known 拉取登记",
    "card approved": "名片已通过审批",
    "card rejected": "名片已拒绝",
    heartbeat: "心跳",
    probe: "探活",
    disable: "停用",
    deprecate: "已弃用",
    enable: "启用",
    "new agent key issued": "已签发新密钥",
    "registered via agent push": "智能体主动登记",
    "registered via hub form": "管理台填入登记",
    "agent deleted": "智能体已删除",
  };

  const INVOKE_STATUS = { ok: "成功", denied: "拒绝", error: "失败" };

  const EFFECT_LABELS = {
    none: "无",
    read: "只读",
    readonly: "只读",
    "read-only": "只读",
  };

  function actionLabel(value) {
    const key = String(value || "").toLowerCase();
    return ACTION_LABELS[key] || value || "未知";
  }

  function summaryLabel(value) {
    const raw = String(value || "");
    const key = raw.toLowerCase();
    if (SUMMARY_LABELS[key]) return SUMMARY_LABELS[key];
    const invoke = raw.match(/^(\S+) -> (\S+) #(\S+) (\S+)$/);
    if (invoke) {
      return invoke[1] + " → " + invoke[2] + "，技能 " + invoke[3] + "，" + (INVOKE_STATUS[invoke[4]] || invoke[4]);
    }
    return raw;
  }

  function effectLabel(value) {
    const key = String(value || "").toLowerCase();
    return EFFECT_LABELS[key] || value || "";
  }

  function chipLabel(kind, value) {
    const key = String(value || "").toLowerCase();
    const map = CHIP_LABELS[kind] || {};
    return map[key] || "未知";
  }

  function statusLabel(item) {
    const status = item.runtime_status || "unknown";
    return badge(status, chipLabel("status", status));
  }

  function sourceLabel(item) {
    const source = item.enrollment_source || "";
    return badge(source === "self" ? "self" : "hub", chipLabel("source", source));
  }

  function lifecycleLabel(item) {
    const lifecycle = item.lifecycle || "unknown";
    return badge(lifecycle, chipLabel("lifecycle", lifecycle));
  }

  function discoveryLabel(item) {
    const status = item.approval_status || "";
    if (status === "rejected") return badge("rejected", chipLabel("approval", "rejected"));
    if (status === "pending" || item.discovery === "approval_required") {
      return badge("pending", chipLabel("approval", "pending"));
    }
    if (item.discovery === "private") return badge("private", chipLabel("discovery", "private"));
    if (status === "approved") return badge("approved", chipLabel("approval", "approved"));
    return "";
  }

  function setGateMode(on) {
    document.body.classList.toggle("is-login", !!on);
  }

  function showLoginError(message) {
    const err = document.getElementById("login-err");
    if (!err) return;
    err.textContent = message || "";
    err.classList.toggle("is-on", !!message);
  }

  function loginErrorText(raw) {
    const msg = String(raw || "");
    if (msg === "invalid username or password") return "用户名或密码错误";
    if (msg === "session expired" || msg === "hub login required") return "请重新登录";
    return msg || "连接失败";
  }

  function bindRoleHelp() {
    const dialog = document.getElementById("role-help");
    const openBtn = document.getElementById("role-help-btn");
    const closeBtn = document.getElementById("role-help-close");
    const userInput = document.getElementById("login-username");
    if (!dialog) return;

    function openHelp() {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    function closeHelp() {
      if (typeof dialog.close === "function" && dialog.open) dialog.close();
      else dialog.removeAttribute("open");
    }

    if (openBtn) openBtn.onclick = openHelp;
    if (closeBtn) closeBtn.onclick = closeHelp;
    dialog.addEventListener("click", function (ev) {
      if (ev.target === dialog) closeHelp();
    });
    dialog.querySelectorAll(".role-card").forEach(function (card) {
      card.onclick = function () {
        if (userInput) {
          userInput.value = (card.getAttribute("data-account") || "").trim();
          userInput.focus();
        }
        closeHelp();
      };
    });
  }

  function motionReduced() {
    const mode = document.documentElement.getAttribute("data-motion") || "system";
    if (mode === "reduce") return true;
    if (mode === "ok") return false;
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function openNativeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function closeNativeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  function playAgentCardGather(onReady) {
    const bits = document.getElementById("login-bits");
    const btn = document.getElementById("agent-card-btn");
    if (!btn) return;
    const reduce = motionReduced();
    const count = reduce ? 0 : 128;
    if (bits) {
      bits.innerHTML = "";
      for (let i = 0; i < count; i += 1) {
        const el = document.createElement("span");
        el.className = "login-bit";
        el.textContent = i % 2 === 0 ? "0" : "1";
        const angle = (Math.PI * 2 * i) / count + (Math.random() * 0.7 - 0.35);
        const dist = 40 + Math.random() * 300;
        el.style.setProperty("--dx", Math.round(Math.cos(angle) * dist) + "px");
        el.style.setProperty("--dy", Math.round(Math.sin(angle) * dist) + "px");
        el.style.setProperty("--rot", Math.round(Math.random() * 720 - 360) + "deg");
        el.style.setProperty("--delay", (Math.random() * 1.1).toFixed(2) + "s");
        el.style.setProperty("--dur", (3.1 + Math.random() * 2.1).toFixed(2) + "s");
        bits.appendChild(el);
      }
    }
    function ready() {
      if (bits) bits.classList.add("is-gone");
      btn.classList.add("is-ready");
      btn.disabled = false;
      btn.setAttribute("aria-busy", "false");
      if (onReady) onReady();
    }
    if (reduce) {
      btn.classList.add("is-forming", "is-ready");
      ready();
      return;
    }
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    window.requestAnimationFrame(function () {
      if (bits) bits.classList.add("is-visible");
    });
    window.setTimeout(function () {
      if (bits) bits.classList.add("is-gathering");
      btn.classList.add("is-forming");
    }, 1440);
    window.setTimeout(ready, 6800);
  }

  function loginView(error) {
    setGateMode(true);
    if (account) account.hidden = true;
    main.innerHTML =
      '<section class="login-page">' +
        '<div class="login-visual" aria-hidden="true">' +
          '<img class="login-avatar" src="/assets/login-handshake.png?v=6" width="1920" height="1080" alt="" />' +
        "</div>" +
        '<div class="login-gather">' +
          '<div class="login-bits" id="login-bits" aria-hidden="true"></div>' +
          '<button type="button" class="agent-card-btn" id="agent-card-btn" disabled aria-busy="true" aria-haspopup="dialog" aria-controls="login-dialog" aria-label="Agent Card，点击打开登录">' +
            '<span class="agent-card-face">' +
              '<span class="agent-card-title">Agent</span>' +
              '<span class="agent-card-title">Card</span>' +
            "</span>" +
            '<span class="agent-card-hint">点击打开登录</span>' +
          "</button>" +
        "</div>" +
        '<footer class="login-foot">SUNNY · Agent Hub · <a href="/help/">文档门户</a></footer>' +
      "</section>" +
      '<dialog class="login-dialog" id="login-dialog" aria-labelledby="login-title">' +
        '<div class="login-card">' +
          '<div class="login-card-head">' +
            '<h1 id="login-title">登录</h1>' +
            '<button type="button" class="role-help-btn" id="role-help-btn">权限说明</button>' +
          "</div>" +
          '<form id="login-form" autocomplete="on">' +
            '<label class="login-field">' +
              '<span class="login-field-label">用户名</span>' +
              '<input class="login-field-input" id="login-username" type="text" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required placeholder="请输入用户名" />' +
            "</label>" +
            '<label class="login-field">' +
              '<span class="login-field-label">密码</span>' +
              '<input class="login-field-input" id="login-password" type="password" name="password" autocomplete="current-password" required />' +
            "</label>" +
            '<button type="submit" class="login-submit">登录</button>' +
          "</form>" +
          '<p class="login-err" id="login-err"></p>' +
        "</div>" +
      "</dialog>" +
      '<dialog class="role-help" id="role-help" aria-labelledby="role-help-title">' +
        '<div class="role-help-panel">' +
          '<div class="role-help-head">' +
            '<h2 id="role-help-title">角色权限说明</h2>' +
            '<button type="button" class="role-help-close" id="role-help-close">关闭</button>' +
          "</div>" +
          '<div class="roles">' +
            '<button type="button" class="role-card" data-role="admin" data-account="admin">' +
              '<span class="role-label">管理员</span>' +
              '<span class="role-accounts">admin</span>' +
              '<span class="role-desc">全部权限</span>' +
            "</button>" +
            '<button type="button" class="role-card" data-role="developer" data-account="developer">' +
              '<span class="role-label">开发者</span>' +
              '<span class="role-accounts">developer</span>' +
              '<span class="role-desc">查看名片，发布并维护自己创建的智能体</span>' +
            "</button>" +
          "</div>" +
        "</div>" +
      "</dialog>";
    bindRoleHelp();
    const loginDialog = document.getElementById("login-dialog");
    const agentBtn = document.getElementById("agent-card-btn");
    function openLoginDialog() {
      openNativeDialog(loginDialog);
      const userInput = document.getElementById("login-username");
      if (userInput) userInput.focus();
    }
    if (agentBtn) agentBtn.onclick = openLoginDialog;
    if (loginDialog) {
      loginDialog.addEventListener("click", function (ev) {
        if (ev.target === loginDialog) closeNativeDialog(loginDialog);
      });
    }
    playAgentCardGather(function () {
      if (error) {
        showLoginError(loginErrorText(error));
        openLoginDialog();
      }
    });
    document.getElementById("login-form").onsubmit = async function (ev) {
      ev.preventDefault();
      showLoginError("");
      try {
        const data = await api("/api/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: document.getElementById("login-username").value.trim(),
            password: document.getElementById("login-password").value,
          }),
        });
        closeNativeDialog(loginDialog);
        setSession(data.token, data.user);
        const dest = "#/" + safeLoginNext(route().query.get("next"));
        if ((location.hash || "") === dest) render();
        else location.hash = dest;
      } catch (e) {
        showLoginError(loginErrorText(e.message));
      }
    };
  }

  function repoCard(item) {
    const tags = (item.skills || []).slice(0, 4).map(function (s) {
      return '<span class="tag">' + escapeHtml(s.id) + "</span>";
    }).join("");
    return (
      '<article class="repo" data-id="' + escapeHtml(item.agent_id) + '">' +
        '<div class="repo-head">' +
          "<div><h2>" + escapeHtml(item.name) + '</h2><div class="id mono">' + escapeHtml(item.agent_id) + "</div></div>" +
          '<div class="badges">' + statusLabel(item) + sourceLabel(item) + discoveryLabel(item) + "</div>" +
        "</div>" +
        "<p>" + escapeHtml(item.description) + "</p>" +
        '<div class="tags">' + tags + "</div>" +
        (item.owner_username ? '<div class="owner">创建者 ' + escapeHtml(item.owner_username) + "</div>" : "") +
        '<div class="meta"><span>' + escapeHtml(item.workspace) + "</span><span>" + (item.skill_count || 0) + " 个技能</span></div>" +
      "</article>"
    );
  }

  async function exploreView(query) {
    const q = query.get("q") || "";
    const source = query.get("source") || "";
    const status = query.get("status") || "";
    const approval = query.get("approval") || "";
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (source) params.set("enrollment_source", source);
    if (status) params.set("runtime_status", status);
    if (approval) params.set("approval_status", approval);
    const data = await api("/api/v1/agents?" + params.toString());
    main.innerHTML =
        '<div class="hero"><div class="hero-copy">' +
        "<h1>智能体 · 名片</h1>" +
        '<ul class="hero-points">' +
          "<li>登记注册</li>" +
          '<li class="is-card">名片卡片</li>' +
          "<li>是否可用</li>" +
          "<li>接入方式</li>" +
        "</ul>" +
        "<p>智能体的卡片就是它的【名片】。在注册中心交换名片之后，才能像人类交换名片那样对等沟通、表达意向。" +
        "要用别的智能体，先拿到它的名片再出票去调；看见名片不等于已经能调用。</p>" +
      "</div><div class=\"filters filter-bar\">" +
        sourceSeg(source) + approvalSelect(approval) +
      "</div></div>" +
      (data.items.length
        ? '<div class="grid">' + data.items.map(repoCard).join("") + "</div>"
        : '<div class="empty">还没有匹配的智能体。</div>');
    main.querySelectorAll(".repo").forEach(function (el) {
      el.onclick = function () { location.hash = "#/agents/" + el.getAttribute("data-id"); };
    });
    main.querySelectorAll(".seg-item[data-source]").forEach(function (el) {
      el.onclick = function () {
        const next = new URLSearchParams(query.toString());
        const value = el.getAttribute("data-source");
        if (value) next.set("source", value); else next.delete("source");
        location.hash = "#/explore?" + next.toString();
      };
    });
    const approvalFilter = document.getElementById("approval-filter");
    if (approvalFilter) {
      approvalFilter.onchange = function () {
        const next = new URLSearchParams(query.toString());
        const value = approvalFilter.value;
        if (value) next.set("approval", value); else next.delete("approval");
        location.hash = "#/explore?" + next.toString();
      };
    }
  }

  async function agentView(id, tab) {
    const item = await api("/api/v1/agents/" + encodeURIComponent(id));
    const revisions = await api("/api/v1/agents/" + encodeURIComponent(id) + "/revisions");
    tab = tab || "overview";
    const skills = (item.card.skills || []).map(function (s) {
      const ext = s["x-sunny"] || {};
      return (
        "<tr><td class=\"mono\">" + escapeHtml(s.id) + "</td><td>" + escapeHtml(s.name) +
        "</td><td>" + escapeHtml(effectLabel(ext.side_effects)) +
        "</td><td>" + escapeHtml(ext.data_class || "") +
        "</td><td>" + escapeHtml((s.tags || []).join(", ")) +
        "</td></tr>"
      );
    }).join("");
    const history = revisions.items.map(function (rev) {
      return (
        "<li>" + datetimeHtml(rev.created_at) + "<div>" +
        "<strong>" + escapeHtml(actionLabel(rev.action)) + "</strong> · " + escapeHtml(rev.actor) +
        "<div>" + escapeHtml(summaryLabel(rev.summary)) + "</div></div></li>"
      );
    }).join("");
    const actionsHtml = agentActions(item);
    main.innerHTML =
      '<div class="panel">' +
        '<div class="detail-head">' +
          "<div><h1>" + escapeHtml(item.name) + "</h1>" +
          '<div class="id mono">' + escapeHtml(item.agent_id) + "</div>" +
          '<div class="badges">' + statusLabel(item) + sourceLabel(item) +
          lifecycleLabel(item) + discoveryLabel(item) + "</div></div>" +
          (actionsHtml ? '<div class="actions">' + actionsHtml + "</div>" : "") +
        "</div>" +
        '<div class="tabs">' +
          tabBtn("overview", "概览", tab) +
          tabBtn("card", item.card_view === "public" ? "公开名片" : "完整名片", tab) +
          (item.can_manage ? tabBtn("edit", "编辑", tab) : "") +
          tabBtn("history", "变更历史", tab) +
        "</div>" +
        '<div class="tab-body" id="tab-body"></div>' +
      "</div>";

    const body = document.getElementById("tab-body");
    if (tab === "card") {
      const cardHint = item.card_view === "public"
        ? '<p class="hint">公开名片：已隐藏 restricted 技能。完整卡走鉴权 Extended Card。</p>'
        : (can("manage_all_agents")
          ? '<p class="hint">完整名片。鉴权扩展卡：<a class="mono" href="/api/v1/agents/' +
            encodeURIComponent(id) + '/extended">GET /extended</a></p>'
          : "");
      body.innerHTML = cardHint + "<pre class=\"card-json\">" + escapeHtml(JSON.stringify(item.card, null, 2)) + "</pre>";
    } else if (tab === "edit" && item.can_manage) {
      renderEditor(body, item);
    } else if (tab === "history") {
      body.innerHTML = history ? "<ul class=\"timeline\">" + history + "</ul>" : '<div class="empty">暂无变更。</div>';
    } else {
      body.innerHTML =
        '<dl class="kv">' +
          "<dt>工作空间</dt><dd class=\"mono\">" + escapeHtml(item.workspace) + "</dd>" +
          "<dt>版本</dt><dd>" + escapeHtml(item.version) + "</dd>" +
          "<dt>访问档位</dt><dd>" + escapeHtml(item.access_tier || "") + "</dd>" +
          "<dt>对等可见</dt><dd>" + escapeHtml(chipLabel("discovery", item.discovery || "registered_peers")) + "</dd>" +
          "<dt>审批</dt><dd>" + escapeHtml(chipLabel("approval", item.approval_status || "none")) +
            (item.approval_reason ? " · " + escapeHtml(item.approval_reason) : "") + "</dd>" +
          "<dt>最近心跳</dt><dd>" + datetimeHtml(item.last_heartbeat_at) + "</dd>" +
          "<dt>名片探活</dt><dd>" + probeHtml(item.probe) + "</dd>" +
          (item.card_source_url
            ? "<dt>名片来源 URL</dt><dd class=\"mono\">" + escapeHtml(item.card_source_url) + "</dd>"
            : "") +
          "<dt>更新时间</dt><dd>" + datetimeHtml(item.updated_at) + "</dd>" +
          "<dt>创建者</dt><dd>" + escapeHtml(item.owner_username || "—") + "</dd>" +
        "</dl>" +
        "<h3>技能</h3>" +
        (item.card_view === "public"
          ? '<p class="hint">对等看到公开技能；restricted 技能不在此列表。</p>'
          : (item.has_extended
            ? '<p class="hint">完整名片含 restricted 技能。也可 <a class="mono" href="/api/v1/agents/' +
              encodeURIComponent(id) + '/extended">GET /extended</a></p>'
            : "")) +
        '<div class="edge-list"><table><thead><tr><th>标识</th><th>名称</th><th>副作用</th><th>数据档</th><th>标签</th></tr></thead><tbody>' +
        skills + "</tbody></table></div>";
    }
    document.querySelectorAll(".tabs button").forEach(function (btn) {
      btn.onclick = function () { location.hash = "#/agents/" + id + "/" + btn.getAttribute("data-tab"); };
    });
    const disable = document.getElementById("btn-disable");
    const deprecate = document.getElementById("btn-deprecate");
    const enable = document.getElementById("btn-enable");
    const editBtn = document.getElementById("btn-edit");
    const deleteBtn = document.getElementById("btn-delete");
    const heartbeat = document.getElementById("btn-hb");
    const probeBtn = document.getElementById("btn-probe");
    const refreshBtn = document.getElementById("btn-refresh");
    const approveBtn = document.getElementById("btn-approve");
    const rejectBtn = document.getElementById("btn-reject");
    const ticketBtn = document.getElementById("btn-ticket");
    if (disable) disable.onclick = async function () {
      await api("/api/v1/agents/" + encodeURIComponent(id) + "/disable", { method: "POST", body: "{}" });
      render();
    };
    if (deprecate) deprecate.onclick = async function () {
      await api("/api/v1/agents/" + encodeURIComponent(id) + "/deprecate", { method: "POST", body: "{}" });
      render();
    };
    if (enable) enable.onclick = async function () {
      await api("/api/v1/agents/" + encodeURIComponent(id) + "/enable", { method: "POST", body: "{}" });
      render();
    };
    if (editBtn) editBtn.onclick = function () { location.hash = "#/agents/" + id + "/edit"; };
    if (deleteBtn) deleteBtn.onclick = function () { confirmDelete(item); };
    if (heartbeat) heartbeat.onclick = async function () {
      await api("/api/v1/agents/" + encodeURIComponent(id) + "/heartbeat", { method: "POST", body: "{}" });
      render();
    };
    if (probeBtn) probeBtn.onclick = async function () {
      await api("/api/v1/agents/" + encodeURIComponent(id) + "/probe", { method: "POST", body: "{}" });
      render();
    };
    if (refreshBtn) refreshBtn.onclick = async function () {
      await api("/api/v1/agents/" + encodeURIComponent(id) + "/refresh", { method: "POST", body: "{}" });
      render();
    };
    if (approveBtn) approveBtn.onclick = async function () {
      await api("/api/v1/agents/" + encodeURIComponent(id) + "/approve", { method: "POST", body: "{}" });
      render();
    };
    if (rejectBtn) rejectBtn.onclick = function () { rejectModal(item); };
    if (ticketBtn) ticketBtn.onclick = function () { ticketModal(item); };
  }

  function blankSkill() {
    return {
      id: "",
      name: "",
      description: "",
      tags: ["readonly"],
      examples: [],
      inputModes: ["application/json"],
      outputModes: ["application/json"],
      "x-sunny": {
        data_class: "internal",
        side_effects: "read",
        invoke: { method: "POST", path: "/sunny/invoke/" },
        when_not_to_use: [],
        input_schema: { type: "object", additionalProperties: true, properties: {} },
        output_schema: { type: "object", additionalProperties: true, properties: {} },
      },
    };
  }

  function renderEditor(container, item) {
    const draft = {
      name: item.name,
      version: item.version,
      description: item.description,
      skills: (item.card.skills || []).map(function (skill) {
        return JSON.parse(JSON.stringify(skill));
      }),
    };
    function readHeader() {
      const name = document.getElementById("ed-name");
      if (!name) return;
      draft.name = name.value;
      draft.version = document.getElementById("ed-version").value;
      draft.description = document.getElementById("ed-desc").value;
    }
    function paint() {
      container.innerHTML =
        '<p class="hint">只有管理员或该智能体的创建者可以改说明、增删技能或删除智能体。保存后会写入一张新的名片修订。</p>' +
        '<form id="edit-form">' +
          '<div class="edit-grid">' +
            '<div><label for="ed-name">名称</label><input id="ed-name" type="text" value="' + escapeHtml(draft.name) + '" /></div>' +
            '<div><label for="ed-version">版本</label><input id="ed-version" type="text" value="' + escapeHtml(draft.version) + '" /></div>' +
            '<div class="wide"><label for="ed-desc">说明</label><textarea id="ed-desc" class="short">' + escapeHtml(draft.description) + "</textarea></div>" +
          "</div>" +
          "<h3>技能 / 功能</h3>" +
          '<div class="skill-editor" id="skill-editor"></div>' +
          '<div class="actions" style="margin:12px 0 18px">' +
            controlBtn("添加技能", { id: "add-skill" }) +
          "</div>" +
          '<div class="actions">' +
            controlBtn("保存修改", { variant: "primary", type: "submit" }) +
            (item.can_delete ? controlBtn("删除智能体", { variant: "danger", id: "edit-delete" }) : "") +
          "</div>" +
          '<p class="error" id="edit-err"></p>' +
        "</form>";
      const editor = document.getElementById("skill-editor");
      editor.innerHTML = draft.skills.map(function (skill, index) {
        const ext = skill["x-sunny"] || {};
        return (
          '<article class="skill-card" data-index="' + index + '">' +
            '<div class="skill-card-head"><h3>技能 ' + (index + 1) + "</h3>" +
            controlBtn("删除该技能", { variant: "danger", size: "sm", cls: "rm-skill", extra: 'data-index="' + index + '"' }) + "</div>" +
            '<div class="edit-grid">' +
              '<div><label>标识</label><input class="sk-id" type="text" value="' + escapeHtml(skill.id || "") + '" /></div>' +
              '<div><label>名称</label><input class="sk-name" type="text" value="' + escapeHtml(skill.name || "") + '" /></div>' +
              '<div class="wide"><label>说明</label><textarea class="sk-desc short">' + escapeHtml(skill.description || "") + "</textarea></div>" +
              '<div><label>标签（逗号分隔）</label><input class="sk-tags" type="text" value="' + escapeHtml((skill.tags || []).join(", ")) + '" /></div>' +
              '<div><label>副作用</label><select class="sk-effect">' +
                option("read", "只读", ext.side_effects) +
                option("write", "写入", ext.side_effects) +
                option("execute_sql", "执行 SQL", ext.side_effects) +
              "</select></div>" +
              '<div><label>数据分级</label><select class="sk-class">' +
                option("internal", "内部", ext.data_class) +
                option("public", "公开", ext.data_class) +
                option("restricted", "受限", ext.data_class) +
              "</select></div>" +
              '<div class="wide"><label>输入槽 JSON Schema</label><textarea class="sk-in short">' +
                escapeHtml(JSON.stringify(ext.input_schema || { type: "object" }, null, 2)) + "</textarea></div>" +
              '<div class="wide"><label>输出槽 JSON Schema</label><textarea class="sk-out short">' +
                escapeHtml(JSON.stringify(ext.output_schema || { type: "object" }, null, 2)) + "</textarea></div>" +
            "</div>" +
          "</article>"
        );
      }).join("") || '<div class="empty">还没有技能。请先添加一个。</div>';
      container.querySelectorAll(".rm-skill").forEach(function (btn) {
        btn.onclick = function () {
          readHeader();
          collectSkills();
          draft.skills.splice(parseInt(btn.getAttribute("data-index"), 10), 1);
          paint();
        };
      });
      document.getElementById("add-skill").onclick = function () {
        readHeader();
        collectSkills();
        draft.skills.push(blankSkill());
        paint();
      };
      const del = document.getElementById("edit-delete");
      if (del) del.onclick = function () { confirmDelete(item); };
      document.getElementById("edit-form").onsubmit = async function (ev) {
        ev.preventDefault();
        const err = document.getElementById("edit-err");
        err.textContent = "";
        try {
          readHeader();
          collectSkills();
          if (!draft.skills.length) throw new Error("至少保留一个技能");
          await api("/api/v1/agents/" + encodeURIComponent(item.agent_id), {
            method: "PATCH",
            body: JSON.stringify({
              name: draft.name.trim(),
              description: draft.description.trim(),
              version: draft.version.trim(),
              skills: draft.skills,
            }),
          });
          location.hash = "#/agents/" + item.agent_id + "/overview";
          render();
        } catch (e) {
          err.textContent = e.message;
        }
      };
    }
    function option(value, label, current) {
      return '<option value="' + value + '"' + (current === value ? " selected" : "") + ">" + label + "</option>";
    }
    function collectSkills() {
      const cards = container.querySelectorAll(".skill-card");
      cards.forEach(function (card, index) {
        const prev = draft.skills[index] || blankSkill();
        const ext = prev["x-sunny"] || {};
        let inputSchema = ext.input_schema || { type: "object" };
        let outputSchema = ext.output_schema || { type: "object" };
        try { inputSchema = JSON.parse(card.querySelector(".sk-in").value); }
        catch (e) { throw new Error("技能 " + (index + 1) + " 的输入 Schema 不是合法 JSON"); }
        try { outputSchema = JSON.parse(card.querySelector(".sk-out").value); }
        catch (e) { throw new Error("技能 " + (index + 1) + " 的输出 Schema 不是合法 JSON"); }
        const skillId = card.querySelector(".sk-id").value.trim();
        prev.id = skillId;
        prev.name = card.querySelector(".sk-name").value.trim();
        prev.description = card.querySelector(".sk-desc").value.trim();
        prev.tags = card.querySelector(".sk-tags").value.split(",").map(function (part) { return part.trim(); }).filter(Boolean);
        ext.side_effects = card.querySelector(".sk-effect").value;
        ext.data_class = card.querySelector(".sk-class").value;
        ext.input_schema = inputSchema;
        ext.output_schema = outputSchema;
        ext.invoke = ext.invoke || { method: "POST", path: "/sunny/invoke/" + skillId };
        if (!ext.invoke.path || ext.invoke.path === "/sunny/invoke/") {
          ext.invoke.path = "/sunny/invoke/" + skillId;
        }
        prev["x-sunny"] = ext;
        draft.skills[index] = prev;
      });
    }
    paint();
  }

  function rejectModal(item) {
    modal.classList.remove("hidden");
    modal.innerHTML =
      '<div class="sheet"><h2>拒绝上架</h2>' +
      "<p>拒绝后对等仍不可见。开发者改卡会重新进入待审批。</p>" +
      '<label>原因</label><textarea id="reject-reason" class="short" placeholder="写给创建者看的原因"></textarea>' +
      '<p class="error" id="reject-err"></p>' +
      '<div class="actions">' +
        controlBtn("确认拒绝", { variant: "danger", id: "reject-go" }) +
        controlBtn("取消", { id: "reject-close" }) +
      "</div></div>";
    document.getElementById("reject-close").onclick = function () { modal.classList.add("hidden"); };
    document.getElementById("reject-go").onclick = async function () {
      const err = document.getElementById("reject-err");
      err.textContent = "";
      const reason = document.getElementById("reject-reason").value.trim();
      if (!reason) {
        err.textContent = "请填写拒绝原因";
        return;
      }
      try {
        await api("/api/v1/agents/" + encodeURIComponent(item.agent_id) + "/reject", {
          method: "POST",
          body: JSON.stringify({ reason: reason }),
        });
        modal.classList.add("hidden");
        render();
      } catch (e) {
        err.textContent = e.message;
      }
    };
  }

  function confirmDelete(item) {
    modal.classList.remove("hidden");
    modal.innerHTML =
      '<div class="sheet"><h2>删除智能体</h2>' +
      "<p>将删除 <strong>" + escapeHtml(item.name) + "</strong>（" + escapeHtml(item.agent_id) + "）。名片与技能会从目录里移除，此操作不能恢复。</p>" +
      '<p class="error" id="del-err"></p>' +
      '<div class="actions">' +
        controlBtn("确认删除", { variant: "danger", id: "del-go" }) +
        controlBtn("取消", { id: "del-close" }) +
      "</div></div>";
    document.getElementById("del-close").onclick = function () { modal.classList.add("hidden"); };
    document.getElementById("del-go").onclick = async function () {
      const err = document.getElementById("del-err");
      err.textContent = "";
      try {
        await api("/api/v1/agents/" + encodeURIComponent(item.agent_id), { method: "DELETE" });
        modal.classList.add("hidden");
        location.hash = "#/explore";
      } catch (e) {
        err.textContent = e.message;
      }
    };
  }

  function tabBtn(id, label, current) {
    return (
      '<button type="button" class="tab' + (current === id ? " active" : "") +
      '" data-tab="' + id + '" aria-current="' + (current === id ? "page" : "false") + '">' +
      label + "</button>"
    );
  }

  function agentActions(item) {
    const manage = [];
    if (item.can_manage) manage.push(controlBtn("编辑", { variant: "primary", id: "btn-edit" }));
    if (item.can_manage && item.card_source_url) manage.push(controlBtn("刷新名片", { id: "btn-refresh" }));
    if (item.can_delete) manage.push(controlBtn("删除", { variant: "danger", id: "btn-delete" }));
    if (can("disable_agents")) {
      if (item.lifecycle === "disabled") {
        manage.push(controlBtn("启用", { variant: "success", id: "btn-enable" }));
      } else if (item.lifecycle === "deprecated") {
        manage.push(controlBtn("恢复", { variant: "success", id: "btn-enable" }));
        manage.push(controlBtn("停用", { variant: "warning", id: "btn-disable" }));
      } else {
        manage.push(controlBtn("弃用", { variant: "warning", id: "btn-deprecate" }));
        manage.push(controlBtn("停用", { variant: "warning", id: "btn-disable" }));
      }
    }
    if (can("approve_agents") && (item.approval_status === "pending" || item.discovery === "approval_required")) {
      manage.push(controlBtn("通过", { variant: "success", id: "btn-approve" }));
      if (item.approval_status !== "rejected") {
        manage.push(controlBtn("拒绝", { variant: "danger", id: "btn-reject" }));
      }
    }
    const extra = [];
    if (can("manage_all_agents")) extra.push(controlBtn("发送心跳", { id: "btn-hb" }));
    if (can("manage_all_agents")) extra.push(controlBtn("探活名片", { id: "btn-probe" }));
    if (can("issue_tickets") && item.lifecycle === "registered") extra.push(controlBtn("签发调用票", { id: "btn-ticket" }));
    const gap = manage.length && extra.length ? '<span class="actions-gap" aria-hidden="true"></span>' : "";
    return manage.join("") + gap + extra.join("");
  }

  function ticketModal(item) {
    const options = (item.skills || []).map(function (s) {
      return "<option value=\"" + escapeHtml(s.id) + "\">" + escapeHtml(s.id) + "</option>";
    }).join("");
    modal.classList.remove("hidden");
    modal.innerHTML =
      '<div class="sheet"><h2>签发短时调用票</h2>' +
      "<p>票绑定 caller / callee / skill，不经过 Registry 转发调用。</p>" +
      '<label>调用方标识</label><input id="tk-caller" type="text" value="lab.inspector" />' +
      "<label>技能</label><select id=\"tk-skill\">" + options + "</select>" +
      '<div class="actions" style="margin-top:14px">' +
        controlBtn("签发", { variant: "primary", id: "tk-go" }) +
        controlBtn("关闭", { id: "tk-close" }) +
      "</div><pre class=\"card-json\" id=\"tk-out\" hidden></pre></div>";
    document.getElementById("tk-close").onclick = function () { modal.classList.add("hidden"); };
    document.getElementById("tk-go").onclick = async function () {
      const data = await api("/api/v1/tickets", {
        method: "POST",
        body: JSON.stringify({
          caller_id: document.getElementById("tk-caller").value.trim(),
          callee_id: item.agent_id,
          skill_id: document.getElementById("tk-skill").value,
        }),
      });
      const out = document.getElementById("tk-out");
      out.hidden = false;
      out.textContent = JSON.stringify(data, null, 2);
    };
  }

  async function networkView() {
    const data = await api("/api/v1/graph");
    const rows = data.edges.map(function (e) {
      return "<tr><td class=\"mono\">" + escapeHtml(e.caller_id) + "</td><td class=\"mono\">" +
        escapeHtml(e.callee_id) + "</td><td class=\"mono\">" + escapeHtml(e.skill_id) +
        "</td><td>" + e.ticket_count + "</td><td>" + e.invoke_count + "</td><td>" +
        datetimeHtml(e.last_at) + "</td></tr>";
    }).join("");
    main.innerHTML =
      '<div class="hero"><div><h1>调用关系</h1><p>注册中心不转发请求。这里统计签发的调用票和上报的调用。</p></div></div>' +
      '<div class="panel graph">' + renderSvg(data) +
      (rows
        ? '<div class="edge-list"><table><thead><tr><th>调用方</th><th>被调方</th><th>技能</th><th>调用票</th><th>调用次数</th><th>最近时间</th></tr></thead><tbody>' +
          rows + "</tbody></table></div>"
        : '<div class="empty">还没有调用边。签发一张调用票或上报一次调用后会出现。</div>') +
      "</div>";
  }

  function renderSvg(data) {
    const nodes = data.nodes || [];
    if (!nodes.length) return "";
    const w = 1040, h = 280;
    const placed = nodes.map(function (n, i) {
      const angle = (Math.PI * 2 * i) / nodes.length - Math.PI / 2;
      return {
        id: n.agent_id,
        x: w / 2 + Math.cos(angle) * 180,
        y: h / 2 + Math.sin(angle) * 90,
        source: n.enrollment_source,
      };
    });
    const byId = {};
    placed.forEach(function (p) { byId[p.id] = p; });
    const lines = (data.edges || []).map(function (e) {
      const a = byId[e.caller_id], b = byId[e.callee_id];
      if (!a || !b) return "";
      return '<line x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y +
        '" stroke="#2496ed" stroke-width="2" marker-end="url(#arrow)" />';
    }).join("");
    const dots = placed.map(function (p) {
      const color = p.source === "self" ? "#0e8a74" : "#1d63ed";
      return '<circle cx="' + p.x + '" cy="' + p.y + '" r="16" fill="' + color + '"></circle>' +
        '<text x="' + p.x + '" y="' + (p.y + 32) + '" text-anchor="middle" font-size="12" fill="#1a1a1a">' +
        escapeHtml(p.id) + "</text>";
    }).join("");
    return '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" height="280">' +
      '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">' +
      '<path d="M 0 0 L 10 5 L 0 10 z" fill="#2496ed" /></marker></defs>' + lines + dots + "</svg>";
  }

  function kindSeg(kind) {
    return (
      '<div class="seg" role="group" aria-label="按事件类型筛选">' +
      [
        ["", "全部"],
        ["search", "搜索"],
        ["ticket", "出票"],
        ["invoke", "调用"],
        ["card", "名片"],
      ].map(function (pair) {
        const selected = kind === pair[0];
        return (
          '<button type="button" class="seg-item' + (selected ? " active" : "") +
          '" data-kind="' + pair[0] + '" aria-pressed="' + (selected ? "true" : "false") + '">' +
          pair[1] + "</button>"
        );
      }).join("") +
      "</div>"
    );
  }

  function kindBadge(kind, status) {
    if (kind === "search") return badge("hub", "搜索");
    if (kind === "ticket") return badge(status === "denied" ? "danger" : "ok", status === "denied" ? "出票拒绝" : "出票");
    if (kind === "invoke") return badge(status === "ok" ? "ok" : "danger", status === "ok" ? "调用成功" : "调用" + (INVOKE_STATUS[status] || status));
    return badge("", actionLabel(kind));
  }

  function activityHash(kind, traceId, q) {
    const params = new URLSearchParams();
    if (kind) params.set("kind", kind);
    if (traceId) params.set("trace_id", traceId);
    if (q) params.set("q", q);
    const qs = params.toString();
    return "#/activity" + (qs ? "?" + qs : "");
  }

  async function activityView(query) {
    query = query || new URLSearchParams();
    const kind = query.get("kind") || "";
    const traceId = query.get("trace_id") || "";
    const q = query.get("q") || "";
    const params = new URLSearchParams();
    if (kind) params.set("kind", kind);
    if (traceId) params.set("trace_id", traceId);
    if (q) params.set("q", q);
    const data = await api("/api/v1/activity?" + params.toString());
    const items = (data.items || []).map(function (ev) {
      const trace = ev.trace_id
        ? '<a class="mono" href="' + activityHash(kind, ev.trace_id, q) + '">' + escapeHtml(ev.trace_id) + "</a>"
        : "";
      const pair = (ev.caller_id || ev.callee_id)
        ? '<span class="mono">' + escapeHtml(ev.caller_id || "—") + " → " + escapeHtml(ev.callee_id || ev.agent_id || "—") + "</span>"
        : '<span class="mono">' + escapeHtml(ev.agent_id || "") + "</span>";
      return "<li>" + datetimeHtml(ev.created_at) + "<div>" + kindBadge(ev.kind, ev.status) + " " +
        pair + (ev.skill_id ? " · <span class=\"mono\">" + escapeHtml(ev.skill_id) + "</span>" : "") +
        (trace ? " · " + trace : "") +
        "<div>" + escapeHtml(summaryLabel(ev.summary)) + " · " + escapeHtml(ev.actor) + "</div></div></li>";
    }).join("");
    main.innerHTML =
      '<div class="hero"><div><h1>动态</h1><p>搜索、出票、调用与名片变更在同一条时间线。点 <code>trace_id</code> 可对账。</p></div>' +
        '<div class="filters">' + kindSeg(kind) +
          '<form id="trace-filter">' +
            '<label class="sr-only" for="trace-id">按 trace_id 过滤</label>' +
            '<input id="trace-id" name="trace_id" type="search" placeholder="按 trace_id 对账…" value="' + escapeHtml(traceId) + '" />' +
            controlBtn("查看", { variant: "primary", type: "submit" }) +
          "</form></div></div>" +
      '<div class="panel">' + (items ? "<ul class=\"timeline\">" + items + "</ul>" : '<div class="empty">暂无活动。</div>') + "</div>";
    document.querySelectorAll("[data-kind]").forEach(function (btn) {
      btn.onclick = function () {
        location.hash = activityHash(btn.getAttribute("data-kind") || "", traceId, q);
      };
    });
    const form = document.getElementById("trace-filter");
    if (form) {
      form.onsubmit = function (ev) {
        ev.preventDefault();
        location.hash = activityHash(kind, document.getElementById("trace-id").value.trim(), q);
      };
    }
  }

  function downloadText(filename, text, type) {
    const blob = new Blob([text], { type: type || "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function fetchJoinMarkdown(includeToken) {
    const path = "/api/v1/join.md" + (includeToken ? "?include_token=1" : "");
    const res = await fetch(path, { headers: includeToken ? headers() : {} });
    const text = await res.text();
    if (!res.ok) {
      let detail = text;
      try { detail = JSON.parse(text).detail || text; } catch (e) {}
      throw new Error(typeof detail === "string" ? detail : "导出失败");
    }
    return text;
  }

  let publishGestures = null;

  function cardJsonPlaceholder() {
    return JSON.stringify({
      name: "AI 数据智能体",
      description: "对外只提供采集策略枚举查询与 ai_collect 余量查询；不开放模型调用、CVAT 建任务或现场 SQL。",
      version: "0.1.0",
      supportedInterfaces: [
        {
          url: "https://aidata.internal.example/sunny/v1",
          protocolBinding: "HTTP+JSON",
          protocolVersion: "1.0",
        },
      ],
      capabilities: { streaming: false, pushNotifications: false },
      defaultInputModes: ["application/json"],
      defaultOutputModes: ["application/json"],
      skills: [
        {
          id: "collect.strategy.query",
          name: "采集策略查询",
          description: "按 mission_name 或关键词查闭环采集策略枚举。检索域锁在策略表与 ai_collect 字典。",
          tags: ["collect", "strategy", "readonly"],
          examples: ["living_room 是什么采集策略"],
          "x-sunny": {
            data_class: "internal",
            side_effects: "read",
            input_schema: {
              type: "object",
              additionalProperties: false,
              anyOf: [{ required: ["query"] }, { required: ["mission_name"] }],
              properties: {
                query: { type: "string" },
                mission_name: { type: "string", description: "如 living_room" },
                product_line: { type: "string", enum: ["deebot", "lawnmower"] },
                trace_id: { type: "string" },
              },
            },
            output_schema: {
              type: "object",
              required: ["ready", "mock", "items", "trace_id"],
              properties: {
                ready: { type: "boolean" },
                mock: { type: "boolean" },
                items: { type: "array" },
                trace_id: { type: "string" },
              },
            },
          },
        },
        {
          id: "collect.volume.query",
          name: "采集数据量查询",
          description: "按白名单槽查询 ai_collect 余量（count）。不返回预览图，不创建 CVAT 任务。",
          tags: ["collect", "volume", "readonly"],
          examples: ["living_room 在机型 0gxgac 还有多少图"],
          "x-sunny": {
            data_class: "internal",
            side_effects: "read",
            input_schema: {
              type: "object",
              additionalProperties: false,
              anyOf: [{ required: ["mission_name"] }, { required: ["robotType"] }],
              properties: {
                mission_name: { type: "string" },
                robotType: { type: "array", items: { type: "string" } },
                quest_name: { type: "string" },
                trace_id: { type: "string" },
              },
            },
            output_schema: {
              type: "object",
              required: ["ready", "mock", "count", "trace_id"],
              properties: {
                ready: { type: "boolean" },
                mock: { type: "boolean" },
                count: { type: "integer" },
                trace_id: { type: "string" },
              },
            },
          },
        },
      ],
      "x-sunny": {
        agent_id: "your.org.aidata",
        workspace: "ecovacs.aidata",
        discovery: "registered_peers",
        access_tier: "S1",
        lifecycle: "draft",
        invoke_auth: "sunny_ticket",
        invoke_identity: "agent_service",
        scratch_access: "none",
        not_exposed: ["model.invoke", "cvat.create_special_task", "hermes.chat"],
      },
    }, null, 2);
  }

  function applyCardJsonPlaceholder() {
    const text = cardJsonPlaceholder();
    const el = document.getElementById("card-json");
    if (el) {
      el.classList.add("card-json-input");
      el.setAttribute("placeholder", text);
    }
  }

  function publishPages() {
    return [
      { id: "hub", label: "主动登记" },
      { id: "pull", label: "网址同步" },
      { id: "join", label: "发给智能体" },
    ];
  }

  function resolvePublishTab(section, pages) {
    for (let i = 0; i < pages.length; i += 1) {
      if (pages[i].id === section) return pages[i].id;
    }
    return pages[0].id;
  }

  function releasePublishGestures() {
    if (publishGestures) {
      publishGestures.abort();
      publishGestures = null;
    }
  }

  function discoveryOptions(includeKeep) {
    return (
      (includeKeep
        ? '<option value="">沿用 Card</option><option value="registered_peers">登记后对等可见</option>'
        : '<option value="registered_peers">登记后对等可见（默认）</option>') +
      '<option value="approval_required">需审批后可见</option>' +
      '<option value="private">仅自己与管理员</option>'
    );
  }

  function syncPublishPagerHeight(animate) {
    const pager = document.getElementById("publish-pager");
    const track = document.getElementById("publish-track");
    if (!pager || !track) return;
    const idx = Number(pager.getAttribute("data-index") || "0");
    const page = track.children[idx];
    if (!page) return;
    const reduce = motionReduced() || !animate;
    pager.classList.toggle("no-anim", reduce);
    pager.style.height = page.offsetHeight + "px";
  }

  function applyPublishTab(tab, opts) {
    opts = opts || {};
    const pages = publishPages();
    const resolved = resolvePublishTab(tab, pages);
    const idx = pages.findIndex(function (page) { return page.id === resolved; });
    const pager = document.getElementById("publish-pager");
    const track = document.getElementById("publish-track");
    if (!pager || !track || idx < 0) return resolved;
    pager.setAttribute("data-index", String(idx));
    pager.setAttribute("data-tab", resolved);
    const reduce = motionReduced() || opts.animate === false;
    track.classList.toggle("no-anim", reduce);
    track.style.transform = "translateX(" + (-idx * 100) + "%)";
    main.querySelectorAll(".publish-tabs .tab").forEach(function (link) {
      const on = link.getAttribute("data-tab") === resolved;
      link.classList.toggle("active", on);
      link.setAttribute("aria-selected", on ? "true" : "false");
    });
    Array.prototype.forEach.call(track.children, function (page, i) {
      const on = i === idx;
      page.classList.toggle("active", on);
      page.setAttribute("aria-hidden", on ? "false" : "true");
      if (page.inert !== undefined) page.inert = !on;
    });
    window.requestAnimationFrame(function () {
      syncPublishPagerHeight(opts.animate !== false);
    });
    const want = "#/publish/" + resolved;
    if (location.hash !== want) history.replaceState(null, "", want);
    return resolved;
  }

  function bindPublishPager() {
    const pager = document.getElementById("publish-pager");
    const track = document.getElementById("publish-track");
    if (!pager || !track) return;
    releasePublishGestures();
    publishGestures = new AbortController();
    const sig = { signal: publishGestures.signal };
    if (typeof ResizeObserver === "function") {
      const ro = new ResizeObserver(function () { syncPublishPagerHeight(false); });
      Array.prototype.forEach.call(track.children, function (page) { ro.observe(page); });
      publishGestures.signal.addEventListener("abort", function () { ro.disconnect(); });
    } else {
      window.addEventListener("resize", function () { syncPublishPagerHeight(false); }, sig);
    }
  }

  function bindPublishForms() {
    async function exportJoin(includeToken) {
      const err = document.getElementById("join-err");
      err.textContent = "";
      try {
        const text = await fetchJoinMarkdown(includeToken);
        downloadText(includeToken ? "sunny-join.secret.md" : "sunny-join.md", text, "text/markdown;charset=utf-8");
      } catch (e) {
        err.textContent = e.message;
      }
    }
    const exportJoinBtn = document.getElementById("export-join");
    if (exportJoinBtn) exportJoinBtn.onclick = function () { exportJoin(false); };
    const exportToken = document.getElementById("export-join-token");
    if (exportToken) exportToken.onclick = function () { exportJoin(true); };
    const pullForm = document.getElementById("pull-form");
    if (pullForm) {
      pullForm.onsubmit = async function (ev) {
        ev.preventDefault();
        const err = document.getElementById("pull-err");
        err.textContent = "";
        const url = document.getElementById("pull-url").value.trim();
        if (!url) {
          err.textContent = "请填写基址或 Card URL";
          return;
        }
        const body = { url: url };
        const overlay = document.getElementById("pull-agent-id");
        if (overlay && overlay.value.trim()) body.agent_id = overlay.value.trim();
        const pullDisc = document.getElementById("pull-discovery");
        if (pullDisc && pullDisc.value) body.discovery = pullDisc.value;
        try {
          const data = await api("/api/v1/agents/pull", {
            method: "POST",
            body: JSON.stringify(body),
          });
          showOnceKey(data);
        } catch (e) {
          err.textContent = e.message;
        }
      };
    }
    function bindCardForm(formId, jsonId, discoveryId, errId, source) {
      const form = document.getElementById(formId);
      if (!form) return;
      form.onsubmit = async function (ev) {
        ev.preventDefault();
        const err = document.getElementById(errId);
        err.textContent = "";
        let card;
        try { card = JSON.parse(document.getElementById(jsonId).value); }
        catch (e) { err.textContent = "JSON 无法解析"; return; }
        const pubDisc = document.getElementById(discoveryId);
        if (pubDisc && pubDisc.value) {
          if (!card["x-sunny"] || typeof card["x-sunny"] !== "object") card["x-sunny"] = {};
          card["x-sunny"].discovery = pubDisc.value;
        }
        try {
          const res = await fetch("/api/v1/agents", {
            method: "POST",
            headers: headers(),
            body: JSON.stringify({ card: card, enrollment_source: source }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || "登记失败");
          showOnceKey(data);
        } catch (e) {
          err.textContent = e.message;
        }
      };
    }
    bindCardForm("pub", "card-json", "pub-discovery", "pub-err", "hub");
  }

  async function publishView(section) {
    const isAdmin = can("export_enroll_token");
    const pages = publishPages();
    const tab = resolvePublishTab(section, pages);
    const existing = document.getElementById("publish-shell");
    if (existing) {
      applyPublishTab(tab, { animate: true });
      return;
    }

    let join = null;
    try { join = await api("/api/v1/join"); } catch (e) { join = null; }
    const still = route();
    if (still.parts[0] !== "publish") return;
    if (document.getElementById("publish-shell")) {
      applyPublishTab(resolvePublishTab(still.parts[1], pages), { animate: true });
      return;
    }
    const publicUrl = join && join.public_url ? join.public_url : location.origin;
    const lan = ((join && join.lan_urls) || []).map(function (url) {
      return "<code>" + escapeHtml(url) + "</code>";
    }).join(" · ");

    const tabs = pages.map(function (page) {
      const on = page.id === tab;
      return (
        '<a href="#/publish/' + page.id + '" class="tab' + (on ? " active" : "") +
        '" role="tab" data-tab="' + page.id + '" aria-selected="' + (on ? "true" : "false") +
        '" aria-controls="publish-page-' + page.id + '" id="publish-tab-' + page.id + '">' +
        page.label + "</a>"
      );
    }).join("");

    const panels = {
      hub:
        '<form id="pub" class="form">' +
          "<p>用当前登录账号贴名片 JSON。</p>" +
          "<label for=\"pub-discovery\">对等可见</label>" +
          '<select id="pub-discovery">' + discoveryOptions(false) + "</select>" +
          "<label for=\"card-json\">智能体名片 JSON</label>" +
          '<p class="hint">浅灰示例按 AI 数据智能体对外两技能写。改 <code>x-sunny.agent_id</code> 后再登记，不要直接用 <code>aidata.hermes</code>。</p>' +
          '<textarea id="card-json" class="card-json-input" spellcheck="false"></textarea>' +
          '<div class="actions" style="margin-top:14px">' +
            controlBtn("登记", { variant: "primary", type: "submit" }) +
          "</div>" +
          '<p class="error" id="pub-err"></p>' +
        "</form>",
      pull:
        '<form id="pull-form" class="form">' +
          "<p>填写对方基址或名片网址，系统同步名片，不代发业务。</p>" +
          "<label for=\"pull-url\">Card 或 sidecar 基址</label>" +
          '<input id="pull-url" type="url" placeholder="http://10.0.0.8:8091 或 …/.well-known/agent-card.json" />' +
          (isAdmin
            ? "<label for=\"pull-agent-id\">补 agent_id（可选，仅当卡上没有）</label>" +
              '<input id="pull-agent-id" type="text" placeholder="your.org.agent" autocomplete="off" />'
            : "") +
          "<label for=\"pull-discovery\">对等可见</label>" +
          '<select id="pull-discovery">' + discoveryOptions(true) + "</select>" +
          '<div class="actions" style="margin-top:14px">' +
            controlBtn("同步登记", { variant: "primary", type: "submit" }) +
          "</div>" +
          '<p class="error" id="pull-err"></p>' +
        "</form>",
      join:
        '<div id="join-export">' +
          "<p>这页不登记。导出说明，让对方智能体自己来。局域网用下面的基址，不要写 <code>0.0.0.0</code>。</p>" +
          '<p class="mono">基址 ' + escapeHtml(publicUrl) +
            ' · <a href="/api/v1/join.md" target="_blank" rel="noopener">GET /api/v1/join.md</a></p>' +
          '<p>人看的说明：<a href="/help/engineering.html" target="_blank" rel="noopener">工程说明</a> · <a href="/help/api.html" target="_blank" rel="noopener">API 参考</a></p>' +
          (lan ? "<p>局域网候选 " + lan + "</p>" : "") +
          '<div class="actions" style="margin-top:12px">' +
            controlBtn("导出说明", { variant: "primary", id: "export-join" }) +
            (isAdmin ? controlBtn("导出说明（含令牌）", { id: "export-join-token" }) : "") +
          "</div>" +
          '<p class="error" id="join-err"></p>' +
        "</div>",
    };

    const pageHtml = pages.map(function (page) {
      const on = page.id === tab;
      return (
        '<section class="publish-page' + (on ? " active" : "") + '" role="tabpanel" id="publish-page-' +
        page.id + '" data-tab="' + page.id + '" aria-labelledby="publish-tab-' + page.id +
        '" aria-hidden="' + (on ? "false" : "true") + '">' +
          '<div class="panel"><h2>' + escapeHtml(page.label) + "</h2>" + panels[page.id] + "</div>" +
        "</section>"
      );
    }).join("");

    main.innerHTML =
      '<div class="hero"><div><h1>发布智能体</h1><p>' +
        (isAdmin
          ? "用当前登录账号主动登记或做网址同步。发给智能体只导出说明。"
          : "用当前登录账号填写。之后只能改、删自己的智能体。") +
      "</p></div></div>" +
      '<div id="publish-shell">' +
        '<nav class="tabs publish-tabs" role="tablist" aria-label="发布方式">' + tabs + "</nav>" +
        '<div class="publish-pager" id="publish-pager" data-index="' +
          pages.findIndex(function (page) { return page.id === tab; }) +
          '" data-tab="' + tab + '">' +
          '<div class="publish-track" id="publish-track">' + pageHtml + "</div>" +
        "</div>" +
      "</div>";

    applyPublishTab(tab, { animate: false });
    bindPublishForms();
    applyCardJsonPlaceholder();
    bindPublishPager();
  }

  function showOnceKey(data) {
    modal.classList.remove("hidden");
    if (!data.agent_key) {
      modal.innerHTML =
        '<div class="sheet"><h2>已更新 ' + escapeHtml(data.agent_id) + "</h2>" +
        "<p>名片已从 URL 刷新。未重发 Agent key。</p>" +
        '<div class="actions">' + controlBtn("查看名片", { variant: "primary", id: "go-agent" }) + "</div></div>";
    } else {
      modal.innerHTML =
        '<div class="sheet"><h2>已登记 ' + escapeHtml(data.agent_id) + "</h2>" +
        "<p>Agent key 只显示这一次，之后只存哈希。心跳和自更新用它。</p>" +
        '<pre class="card-json">' + escapeHtml(data.agent_key) + "</pre>" +
        '<div class="actions">' + controlBtn("查看名片", { variant: "primary", id: "go-agent" }) + "</div></div>";
    }
    document.getElementById("go-agent").onclick = function () {
      modal.classList.add("hidden");
      location.hash = "#/agents/" + data.agent_id;
    };
  }

  function syncNav() {
    const section = route().parts[0] || "explore";
    const key = section === "agents" ? "explore" : section;
    document.querySelectorAll(".topnav a[data-nav]").forEach(function (link) {
      const nav = link.getAttribute("data-nav");
      const allowed = (
        nav === "explore" ||
        nav === "publish" ||
        nav === "settings" ||
        (nav === "network" && can("view_graph")) ||
        (nav === "activity" && can("view_activity")) ||
        (nav === "users" && can("manage_users"))
      );
      link.hidden = !allowed;
      link.classList.toggle("active", allowed && nav === key);
    });
    if (!account) return;
    if (!currentUser) {
      account.hidden = true;
      account.innerHTML = "";
      return;
    }
    account.hidden = false;
    account.innerHTML =
      '<span class="who">' + escapeHtml(currentUser.username || "") + "</span>" +
      badge(currentUser.role === "admin" ? "admin" : "developer", roleLabel(currentUser.role)) +
      controlBtn("退出", { id: "btn-logout", size: "sm" });
    document.getElementById("btn-logout").onclick = function () {
      clearSession();
      if ((location.hash || "") === "#/login") render();
      else location.hash = "#/login";
    };
  }

  function denyView(message) {
    main.innerHTML = '<div class="empty">' + escapeHtml(message || "当前角色无权访问这一页。") + "</div>";
  }

  function prefSeg(items, selected, attr) {
    return (
      '<div class="seg" role="group">' +
      items.map(function (item) {
        const on = selected === item.id;
        return (
          '<button type="button" class="seg-item' + (on ? " active" : "") +
          '" data-pref="' + escapeHtml(attr) + '" data-value="' + escapeHtml(item.id) +
          '" aria-pressed="' + (on ? "true" : "false") + '">' +
          escapeHtml(item.name) + "</button>"
        );
      }).join("") +
      "</div>"
    );
  }

  function settingsView(section) {
    const tab = ["theme", "type", "display"].indexOf(section) >= 0 ? section : "theme";
    const prefs = readPrefs();
    const nav = [
      ["theme", "主题"],
      ["type", "字体"],
      ["display", "显示"],
    ].map(function (item) {
      return (
        '<a href="#/settings/' + item[0] + '" class="' + (tab === item[0] ? "active" : "") + '">' +
        item[1] + "</a>"
      );
    }).join("");

    let body = "";
    if (tab === "theme") {
      body =
        "<h2>主题设置</h2>" +
        '<p class="settings-lead">五套主题保存在本机，不进账号、不影响出票。浅色是现在的管理台；另外两套是常规深浅，三套是机械风。</p>' +
        '<div class="theme-grid">' +
        THEMES.map(function (theme) {
          const on = prefs.theme === theme.id;
          return (
            '<button type="button" class="theme-card' + (on ? " active" : "") +
            '" data-theme-id="' + theme.id + '" aria-pressed="' + (on ? "true" : "false") + '">' +
            '<span class="theme-swatch theme-swatch-' + theme.id + '" aria-hidden="true"></span>' +
            "<strong>" + escapeHtml(theme.name) + "</strong>" +
            "<span>" + escapeHtml(theme.desc) + "</span></button>"
          );
        }).join("") +
        "</div>";
    } else if (tab === "type") {
      body =
        "<h2>字体</h2>" +
        '<p class="settings-lead">界面字体管标题和正文，等宽字体管标识、时间与 JSON。</p>' +
        '<div class="pref-block"><h3>界面字体</h3>' + prefSeg(FONT_UI, prefs.font, "font") + "</div>" +
        '<div class="pref-block"><h3>等宽字体</h3>' + prefSeg(FONT_MONO, prefs.mono, "mono") + "</div>" +
        '<div class="pref-block"><h3>字号</h3>' + prefSeg(TYPE_SIZES, prefs.typeSize, "typeSize") + "</div>" +
        '<div class="pref-preview"><strong>智能体 · 名片</strong>' +
        '<p class="hint">交换名片之后才能对等沟通。</p>' +
        '<code class="mono">lab.inspector · aidata.hermes</code></div>';
    } else {
      body =
        "<h2>显示</h2>" +
        '<p class="settings-lead">密度改卡片和控件留白。动效管字标闪烁、登录汇聚和发布子页切换，不改出票。</p>' +
        '<div class="pref-block"><h3>密度</h3>' + prefSeg(DENSITIES, prefs.density, "density") + "</div>" +
        '<div class="pref-block"><h3>动效</h3>' + prefSeg(MOTIONS, prefs.motion, "motion") + "</div>" +
        '<div class="actions">' + controlBtn("恢复默认", { id: "btn-prefs-reset" }) + "</div>" +
        '<p class="hint">项目介绍和工程文档在 <a href="/help/" target="_blank" rel="noopener">文档门户</a>，不进顶栏。</p>';
    }

    main.innerHTML =
      '<div class="hero"><div><h1>系统设置</h1><p>主题、字体和显示只作用于这台浏览器上的管理台。</p></div></div>' +
      '<div class="settings"><nav class="settings-nav" aria-label="设置分类">' + nav +
      '</nav><section class="settings-body panel">' + body + "</section></div>";

    main.querySelectorAll("[data-theme-id]").forEach(function (btn) {
      btn.onclick = function () {
        writePrefs({ theme: btn.getAttribute("data-theme-id") });
        settingsView("theme");
      };
    });
    main.querySelectorAll("[data-pref]").forEach(function (btn) {
      btn.onclick = function () {
        const patch = {};
        patch[btn.getAttribute("data-pref")] = btn.getAttribute("data-value");
        writePrefs(patch);
        settingsView(tab);
      };
    });
    const reset = document.getElementById("btn-prefs-reset");
    if (reset) {
      reset.onclick = function () {
        localStorage.removeItem(PREFS_KEY);
        applyPrefs(readPrefs());
        settingsView("display");
      };
    }
  }

  async function usersView() {
    const data = await api("/api/v1/users");
    const rows = data.items.map(function (user) {
      return "<tr><td class=\"mono\">" + escapeHtml(user.username) + "</td><td>" +
        escapeHtml(roleLabel(user.role)) + "</td><td>" + datetimeHtml(user.created_at) +
        "</td><td>" + controlBtn("删除", {
          variant: "danger",
          size: "sm",
          cls: "rm-user",
          extra: 'data-id="' + escapeHtml(user.user_id) + '"',
        }) + "</td></tr>";
    }).join("");
    main.innerHTML =
      '<div class="hero"><div><h1>账号管理</h1><p>管理员可创建开发者账号。开发者只能看名片，并维护自己发布的智能体。</p></div></div>' +
      '<div class="panel"><form id="user-form" class="edit-grid">' +
        '<div><label for="nu-name">用户名</label><input id="nu-name" type="text" autocomplete="off" /></div>' +
        '<div><label for="nu-pass">密码</label><input id="nu-pass" type="password" autocomplete="new-password" /></div>' +
        '<div><label for="nu-role">角色</label><select id="nu-role"><option value="developer">开发者</option><option value="admin">管理员</option></select></div>' +
        '<div style="align-self:end">' + controlBtn("添加账号", { variant: "primary", type: "submit" }) + "</div>" +
      '</form><p class="error" id="user-err"></p></div>' +
      '<div class="panel"><div class="edge-list"><table><thead><tr><th>用户名</th><th>角色</th><th>创建时间</th><th></th></tr></thead><tbody>' +
      rows + "</tbody></table></div></div>";
    document.getElementById("user-form").onsubmit = async function (ev) {
      ev.preventDefault();
      const err = document.getElementById("user-err");
      err.textContent = "";
      try {
        await api("/api/v1/users", {
          method: "POST",
          body: JSON.stringify({
            username: document.getElementById("nu-name").value.trim(),
            password: document.getElementById("nu-pass").value,
            role: document.getElementById("nu-role").value,
          }),
        });
        usersView();
      } catch (e) {
        err.textContent = e.message;
      }
    };
    main.querySelectorAll(".rm-user").forEach(function (btn) {
      btn.onclick = async function () {
        const err = document.getElementById("user-err");
        err.textContent = "";
        try {
          await api("/api/v1/users/" + encodeURIComponent(btn.getAttribute("data-id")), { method: "DELETE" });
          usersView();
        } catch (e) {
          err.textContent = e.message;
        }
      };
    });
  }

  async function ensureSession() {
    if (!token()) {
      currentUser = null;
      return null;
    }
    const me = await api("/api/v1/auth/me");
    currentUser = me;
    sessionStorage.setItem(USER_KEY, JSON.stringify(me));
    return me;
  }

  async function render() {
    try {
      const r = route();
      if (!token() || r.parts[0] !== "publish") releasePublishGestures();
      if (!token()) {
        if (r.parts[0] !== "login") {
          goLogin("", intendedRoutePath(r));
          return;
        }
        syncNav();
        if (!document.querySelector(".login-page")) loginView();
        return;
      }
      await ensureSession();
      setGateMode(false);
      syncNav();
      if (r.parts[0] === "login") {
        const dest = "#/" + safeLoginNext(r.query.get("next"));
        if ((location.hash || "") === dest) return await exploreView(r.query);
        location.hash = dest;
        return;
      }
      if (r.parts[0] === "explore") return await exploreView(r.query);
      if (r.parts[0] === "network") {
        if (!can("view_graph")) return denyView("开发者不能查看调用关系。");
        return await networkView();
      }
      if (r.parts[0] === "activity") {
        if (!can("view_activity")) return denyView("开发者不能查看全局活动动态。");
        return await activityView(r.query);
      }
      if (r.parts[0] === "publish") return await publishView(r.parts[1]);
      if (r.parts[0] === "users") {
        if (!can("manage_users")) return denyView("只有管理员可以管理账号。");
        return await usersView();
      }
      if (r.parts[0] === "settings") return settingsView(r.parts[1]);
      if (r.parts[0] === "agents" && r.parts[1]) return await agentView(r.parts[1], r.parts[2]);
      return await exploreView(r.query);
    } catch (e) {
      if (e.status === 401) {
        releasePublishGestures();
        clearSession();
        goLogin(e.message, intendedRoutePath(route()));
        return;
      }
      setGateMode(false);
      main.innerHTML = '<div class="empty error">' + escapeHtml(e.message) + "</div>";
    }
  }

  document.getElementById("global-search").onsubmit = function (ev) {
    ev.preventDefault();
    const q = document.getElementById("q").value.trim();
    location.hash = "#/explore?" + (q ? "q=" + encodeURIComponent(q) : "");
  };
  window.addEventListener("hashchange", render);
  render();
})();
