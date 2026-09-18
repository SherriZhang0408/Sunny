# SUNNY Registry API（M1）

| 项 | 内容 |
|----|------|
| 基址 | `SUNNY_PUBLIC_URL`；未设则探测局域网 IPv4。监听默认 `0.0.0.0:8088` |
| 管理台 | 同源 `/` |
| 存储 | SQLite（`SUNNY_DB`，默认 `data/sunny.db`） |
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
| GET | `/api/v1/health` | 探活；含 `public_url`、`join` |
| POST | `/api/v1/auth/login` | Hub 登录。body: `{username, password}` |
| GET | `/api/v1/auth/me` | 当前 Hub 用户与权限 |
| GET · POST · DELETE | `/api/v1/users` | 账号管理（管理员） |
| GET | `/api/v1/join` · `/api/v1/join.md` | 握手包。匿名无令牌；`?include_token=1` 需管理员 |
| POST | `/api/v1/agents` | 注册。body: `{card, enrollment_source: self\|hub}`。Hub 用户发布会记 `created_by` |
| GET | `/api/v1/agents` | 列表。管理员可见禁用；开发者/对等只见 `registered` |
| GET | `/api/v1/agents/{id}` | 详情 + Card；含 `can_manage` / `can_delete` |
| PUT | `/api/v1/agents/{id}` | 整卡更新。管理员、创建者或本 Agent key |
| PATCH | `/api/v1/agents/{id}` | 改名称/说明/版本/技能（`skills` 或 `add_skills` / `update_skills` / `remove_skill_ids`） |
| DELETE | `/api/v1/agents/{id}` | 删除。仅管理员或创建该卡的开发者 |
| POST | `/api/v1/agents/{id}/disable` · `/enable` | 下线 / 恢复 |
| POST | `/api/v1/agents/{id}/keys` | 管理员签发新 `sak_`（明文只回这一次） |
| POST | `/api/v1/agents/{id}/heartbeat` | 心跳 |
| GET | `/api/v1/agents/{id}/revisions` | 变更历史 |
| GET | `/api/v1/search` | `skill` `tag` `workspace` `q`；只返回 `discovery=registered_peers` 且只读、`data_class` 为 public/internal 的 skill |
| POST | `/api/v1/tickets` | 签发短时票。载荷含 `card_version`；对等不能调 private / approval_required / restricted / write |
| POST | `/api/v1/tickets/verify` | 验票。Card `version` 变更后旧票作废 |
| POST | `/api/v1/invocations` | 上报一次调用结果（画关系图） |
| GET | `/api/v1/graph` | 节点 + 调用边 |
| GET | `/api/v1/activity` | 管理员时间线。`kind` `trace_id` `q`；搜索 / 出票 / 调用 / 名片 |

Registry **不转发**业务调用。

## 启动

```bash
python3 -m pip install -r requirements.txt
SUNNY_SEED=1 python3 -m sunny_registry
```

空库会种入 `aidata.hermes`（Hub 填入）和 `lab.inspector`（Agent 主动），并有一条演示调用边。
