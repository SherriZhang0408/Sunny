# SUNNY 策略门闩（P0）

| 项 | 内容 |
|----|------|
| 代码 | `sunny_registry/policy.py` |
| 决策 | [ADR-001](../decisions/ADR-001-开写前五件事.md) 发现≠访问；[ADR-002](../decisions/ADR-002-工作空间隔离.md) 升版旧票作废 |

控制面硬编码规则，不另起工作流引擎。管理员可越过对等门闩（出票、看私有卡）。审批只有管理员过 / 拒，没有会签。

## 发现

| `x-sunny.discovery` | 对等搜索 / 列表 / 读卡 / 出票 | 管理员 | 创建者或本 Agent |
|----|------|--------|------------------|
| `registered_peers`（默认） | 可以 | 可以 | 可以 |
| `private` | 否（读卡 404） | 可以 | 可以 |
| `approval_required` | 否，直到管理员通过 | 可以 | 可以（改说明；不能自己通过） |

默认仍是 `registered_peers`；`approval_required` 是可选更严档，不是新默认。

## 生命周期

库字段 `agents.lifecycle`（同步写进 `x-sunny.lifecycle`）。**不是**审批第六态。

| 状态 | 对等读卡 / 搜索 | 出新票 | 验已有票 |
|------|------------------|--------|----------|
| `registered` | 可以（搜索仍默认只要 online） | 可以 | 可以 |
| `deprecated` | 可以 | 否（`409 callee is deprecated`） | 可以（版本未变且未过期） |
| `disabled` | 否（404） | 否（`409 callee is not registered`） | 否 |

管理员：`POST /agents/{id}/deprecate`、`/enable`（回到 `registered`）、`/disable`。已停用的卡不能直接弃用，须先启用。

## 审批状态机

库字段 `approval_status`（另记 `approval_reason` / `approval_decided_at` / `approval_decided_by`）。

| 状态 | 何时 | 对等可见 |
|------|------|----------|
| `none` | 从未走审批（默认 `registered_peers` 或主动选 `private`） | 跟 `discovery` |
| `pending` | 登记/拉取/改卡时 `discovery=approval_required` | 否 |
| `approved` | 管理员 `POST /agents/{id}/approve` → `discovery=registered_peers` | 是（仍要在线心跳才能被搜到） |
| `rejected` | 管理员 `POST /agents/{id}/reject` 带原因；`discovery` 仍为 `approval_required` | 否 |

- 开发者 / 本 Agent **不能**把 `approval_required` 改成 `registered_peers`（`403 cannot self-approve`）。
- 被拒后改卡且仍写 `approval_required` → 回到 `pending`（重新排队）。
- 通过时若没改 Card `version`，旧票仍有效；若同时改了对外技能，应升版本。
- Well-Known 拉取也可 overlay `discovery=approval_required`，进同一待办。

管理员：`GET /api/v1/approvals?status=pending|rejected|approved`。

## 技能

搜索只收 `side_effects=read` 且 `data_class` 为 `public` / `internal`。

读卡分流：对等与非创建者的开发者 `GET /agents/{id}` 只拿公开卡（已剥 restricted）。已登记对等或 Hub 会话可用 `GET /agents/{id}/extended` 看完整卡（可见性仍走 `can_view_agent`）。管理员 / 创建者 / 本 Agent 默认读卡就是完整卡。

对等出票拒绝：`write` / `execute_sql`、`data_class=restricted`、被调方不可被对等发现。**Extended Card 只做披露，不改出票门闩。** 管理员仍可代签。

## 票

载荷除 caller / callee / skill / TTL 外带 `card_version`（被调方当前 Card `version`）。验票时版本对不上或缺版本 → `401 ticket stale: card version changed`。

Card `version` 变化写入 `card_changes`。对等轮询 `GET /api/v1/card-changes?since=`（或 MCP `list_card_changes`）。Registry **不推送**、不回调对方进程。
