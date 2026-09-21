# SUNNY Registry API（M1）

| 项 | 内容 |
|----|------|
| 基址 | `SUNNY_PUBLIC_URL`；未设则探测局域网 IPv4。监听默认 `0.0.0.0:8088` |
| 管理台 | 同源 `/` |
| 存储 | SQLite（`SUNNY_DB`，默认 `data/sunny.db`）；发现用 FTS5 虚表 `agent_fts` |
| 接入说明 | 匿名 `GET /api/v1/join.md`；规格见 [join.md](./join.md) |

## 鉴权

| 身份 | 怎么带 | 能做什么 |
|------|--------|----------|
| 管理员 | 登录 `admin` 或 `Authorization: Bearer $SUNNY_ADMIN_TOKEN` | 全部读写、账号管理、Activity / 关系图、导出 enroll token |
| 开发者 | 登录后带会话 Bearer | 看已登记名片；`hub` 发布自己的智能体；只改/删 `created_by` 是自己的卡 |
| Agent 服务账号 | `X-Sunny-Agent-Key: sak_…` 或 Bearer 同一把 key | 搜已登记对等、读 Card、心跳、更新自己、要票 |
| 首次自注册 | `X-Sunny-Enroll: $SUNNY_ENROLL_TOKEN` | 只允许 `enrollment_source=self` 的创建 |

默认本地账号：`admin` / `sunny-dev-admin`，`developer` / `sunny-dev-developer`。票与 key **不写进 Card**。Hub 角色不进入调用票（ADR-002 / ADR-003）。

## 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 探活；含 `ok`、`service`、`role`、`public_url`、`join`、`agents`、`fts`、`sweep` |
| POST | `/api/v1/auth/login` | Hub 登录。body: `{username, password}` |
| GET | `/api/v1/auth/me` | 当前 Hub 用户与权限 |
| GET · POST | `/api/v1/users` | 账号管理（管理员） |
| DELETE | `/api/v1/users/{user_id}` | 删除账号（管理员；不能删最后一名管理员） |
| GET | `/api/v1/join` · `/api/v1/join.md` | 握手包。匿名无令牌；`?include_token=1` 需管理员；`?download=1` 触发下载 |
| GET · POST | `/mcp` | MCP 发现面。GET 回工具清单与 `instructions`；POST 为 JSON-RPC（`list_agents` / `search_registry` / `get_card` / `get_extended_card` / `describe_access` / `list_card_changes` / `join`）。描述访问方式，不签发票、不代调。stdio：`python3 -m sunny_registry.mcp_stdio`。规格见 [mcp-discovery.md](./mcp-discovery.md) |
| POST | `/api/v1/agents` | 注册。body: `{card, enrollment_source: self\|hub}`。Hub 用户发布会记 `created_by` |
| POST | `/api/v1/agents/pull` | Well-Known 拉取。body: `{url, enrollment_source?, agent_id?, discovery?}`。Hub 用户或 `X-Sunny-Enroll`。管理员可 overlay 缺的 `agent_id`；`discovery` 拉取方可覆盖。拉到的卡仍走 schema / 禁密钥。已存在则刷新（不重发 key） |
| GET | `/api/v1/agents` | 列表。管理员可见禁用；开发者/对等见 `registered` 与 `deprecated`。可滤 `q`、`workspace`、`discovery`、`approval_status`、`enrollment_source`、`runtime_status`；管理员可 `include_disabled`。`q` 与 `/search` 同走 FTS5 |
| GET | `/api/v1/agents/{id}` | 详情 + Card；含 `can_manage` / `can_delete` / `card_view` / `has_extended`。对等与非创建者开发者拿公开卡（剥 restricted）；管理员 / 创建者 / 本 Agent 拿完整卡 |
| GET | `/api/v1/agents/{id}/extended` | 鉴权完整卡。已登记对等（`sak_`）或 Hub 会话；可见性与读卡相同。`ETag` 为 Card `version`；`Vary: Authorization` |
| GET | `/api/v1/agents/{id}/a2a` | 纯 A2A Card：剥掉 `x-sunny`、Sunny 扩展与 restricted 技能。可见性与读卡相同。`ETag` 为 Card `version`；`If-None-Match` 命中回 `304` |
| PUT | `/api/v1/agents/{id}` | 整卡更新。管理员、创建者或本 Agent key |
| PATCH | `/api/v1/agents/{id}` | 改名称/说明/版本/技能（`skills` 或 `add_skills` / `update_skills` / `remove_skill_ids`） |
| DELETE | `/api/v1/agents/{id}` | 删除。仅管理员或创建该卡的开发者 |
| POST | `/api/v1/agents/{id}/disable` · `/deprecate` · `/enable` | 停用（对等 404）/ 弃用（能读卡不能出新票）/ 恢复为 `registered` |
| POST | `/api/v1/agents/{id}/keys` | 管理员签发新 `sak_`（明文只回这一次） |
| POST | `/api/v1/agents/{id}/heartbeat` | 心跳 |
| POST | `/api/v1/agents/{id}/probe` | Card 接口 URL 探活。管理员或本 Agent。探 `/health`、well-known、接口基址；不代发业务。结果写入 `probe` |
| POST | `/api/v1/agents/{id}/refresh` | 用库里的 `card_source_url` 重抓。管理员、创建者或本 Agent。失败保留旧卡 |
| GET | `/api/v1/approvals` | 管理员待办。`status=pending\|rejected\|approved`，默认 pending |
| POST | `/api/v1/agents/{id}/approve` | 管理员通过：`discovery=registered_peers`，`approval_status=approved` |
| POST | `/api/v1/agents/{id}/reject` | 管理员拒绝。body `{reason}`；仍不可见 |
| GET | `/api/v1/agents/{id}/revisions` | 变更历史（对等或 Hub） |
| GET | `/api/v1/agents/{id}/revisions/{rev}` | 某一版 Card 快照（仅管理员） |
| GET | `/api/v1/search` | `skill` `tag` `workspace` `q`；只返回 `discovery=registered_peers` 且只读、`data_class` 为 public/internal 的 skill（`registered` 与 `deprecated` 都可能命中）。**默认只要 `runtime_status=online`**。管理员可 `alive=0`。`q` 走 FTS5。`skill=` 仍是精确 id |
| GET | `/api/v1/card-changes` | Card `version` 变更流。`since` `agent_id` `limit`。对等只看见 `registered_peers` 且可读生命周期的卡。不推送 |
| POST | `/api/v1/tickets` | 签发短时票。载荷含 `card_version`；对等不能调 private / approval_required / restricted / write |
| POST | `/api/v1/tickets/verify` | 验票。Card `version` 变更后旧票作废 |
| POST | `/api/v1/invocations` | 上报一次调用结果（画关系图） |
| GET | `/api/v1/graph` | 节点 + 调用边 |
| GET | `/api/v1/activity` | 管理员时间线。`kind` `trace_id` `q` `limit`（默认 80，上限 200）；搜索 / 出票 / 调用 / 名片 |
| GET | `/` · `/assets/*` | Hub 静态页。其余非 `api/` 路径回 SPA |

Registry **不转发**业务调用。会话令牌不能当调用票：`POST /tickets/verify` 拒 `typ=session` 与缺 caller/callee/skill 的残票。

## 启动

```bash
python3 -m pip install -r requirements.txt
SUNNY_SEED=1 python3 -m sunny_registry
```

空库会种入 `aidata.hermes`（Hub 填入）和 `lab.inspector`（Agent 主动），并有一条演示调用边。

相关环境变量：`SUNNY_HEARTBEAT_STALE_S`（默认 90，超过则 `stale`，搜索默认排除）、`SUNNY_PROBE_TIMEOUT_S`（默认 2，Card URL 探活超时）、`SUNNY_PULL_TIMEOUT_S`（默认 5，Well-Known 拉取超时）、`SUNNY_SWEEP_S`（默认 60，周期探活/重抓；`0` 关闭）、`SUNNY_REFRESH_INTERVAL_S`（默认 300，有 `card_source_url` 才重抓）。探活只 GET `/health`、`/.well-known/agent-card.json` 或接口基址，User-Agent 为 `SUNNY-Registry-Probe/1.0`，不代发 skill。拉取 User-Agent 为 `SUNNY-Registry-Pull/1.0`，规格见 [well-known-pull.md](./well-known-pull.md)。`GET /api/v1/health` 含 `sweep`。
