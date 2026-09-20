# 计划：deprecated + Card 升版订阅

| 项 | 内容 |
|----|------|
| 窗口 | 两段串行：先弃用，再变更流。单开 |
| 学自 | agentoperations 六态只取 `deprecated`；Nacos `subscribeAgentCard` 只学「升版要让调用方知道」 |
| 上游 | [同类项目对照](../research/同类项目对照.md) §7.2；[policy.md](../specs/policy.md) |
| 规格 | 已写入 `policy.md`、`registry-api.md`、`mcp-discovery.md` |
| 现状 | 已落地（2026-09-20） |
| 红线 | Registry 不转发、不做 `/chat`、不把变更推进对方大脑（无 Webhook / 无 IM） |

## 目标

1. **`deprecated`**：对等仍能读卡、能搜到（在线时），**不能出新票**。`disabled` 继续是「对等当没这张卡」。
2. **升版订阅**：Card `version` 一变就记进变更流；对等用 `since` 拉取，MCP 同读。已有 `card_version` 旧票作废保持不动。

## 验收

### 阶段 1 · deprecated

- `lifecycle` 增加 `deprecated`。管理员 `POST /agents/{id}/deprecate`；`POST /enable` 回到 `registered`；`POST /disable` 仍是对等 404。
- 对等：`GET /agents/{id}`、`/extended`、`/a2a` 可读；`/search` 仍能命中（默认只要 online）。
- 对等 / 管理员：`POST /tickets` → `409 callee is deprecated`。
- 弃用前已签发、版本未变的票：`/tickets/verify` 仍可通过，直到 TTL 或升版。
- 管理台：已登记有「弃用」；弃用后有「恢复」；弃用态不提供「签发调用票」。
- pytest：读卡 / 搜索 / 拒新票 / 旧票可验 / 停用仍 404。

### 阶段 2 · 升版变更流

- 改卡或 Well-Known 刷新导致 `version` 变化 → 写入 `card_changes`（old/new/actor）。首次登记不写。
- `GET /api/v1/card-changes?since=&agent_id=`：已登记对等或 Hub；对等只看见 `registered_peers` 且可读生命周期的卡。
- MCP 工具 `list_card_changes`（只读，无票、无 invoke）。
- Join Packet 补一句：依赖某对等后轮询变更流，不要等 Registry 推过来。
- 不做 Nacos 式回调、SSE、Webhook。

## 日程

| 序 | 任务 | 复杂度 |
|----|------|--------|
| 1 | 规格：`policy.md` 生命周期三态对照 | S |
| 2 | `deprecate` API + 出票/验票/搜索/读卡门闩 | M |
| 3 | Hub「弃用 / 恢复」；Join / QA 一句 | S |
| 4 | `card_changes` 表 + `GET /card-changes` + MCP | M |
| 5 | 测试 + 对照文档勾已落地 | S |

## 会改的文件

- `sunny_registry/policy.py`、`store.py`、`db.py`、`app.py`、`mcp.py`、`join.py`
- `web/assets/app.js`
- `tests/test_policy.py`、新 `tests/test_deprecated.py`、`tests/test_card_changes.py`、MCP / Join / Hub UI
- `docs/specs/policy.md`、`registry-api.md`、`mcp-discovery.md`、`join.md`、`qa/hub-manual.md`

## 风险

- 不要把 `deprecated` 做成审批第六态，也不要和 `disabled` 混用。
- 不要为了「订阅」上推送通道；调用方自己的 Skill / 系统提示决定何时来拉。
- `list_agents(only_registered=True)` 必须同时放出 `deprecated`，否则 Hub 对等列表读不到弃用卡。
- 升版仍只靠现有 `card_version` 作废旧票，变更流不替代验票。
