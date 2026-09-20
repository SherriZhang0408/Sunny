# SUNNY 观测（P2）

| 项 | 内容 |
|----|------|
| 代码 | `sunny_registry/observe.py`、`observe_events` 表 |
| 读者 | 管理员 Activity |

控制面记「谁发现了谁、谁拿了票、谁调了谁」。Registry 仍不转发业务调用。票、key、密码不入库。

## 事件

| `kind` | 何时写 | 关键字段 |
|--------|--------|----------|
| `search` | `GET /api/v1/search` | actor、查询槽、命中的 `agent_id`（最多 20） |
| `ticket` | 出票成功或拒绝 | caller / callee / skill / `jti`；拒绝带 `reason` |
| `invoke` | `POST /api/v1/invocations` | `trace_id`、`ticket_jti`、status |
| `card` | 仍读 `revisions`；探活另写入本表 | 登记、改卡、心跳、停用；`POST /probe` 与周期扫记可达/失败（含 url、`category`，不含票） |

## API

`GET /api/v1/activity`（管理员）

| 参数 | 说明 |
|------|------|
| `kind` | `search` / `ticket` / `invoke` / `card` |
| `trace_id` | 精确对账，只回观测事件 |
| `q` | 模糊匹配 actor / 双方 / skill / 摘要 |
| `limit` | 默认 80，最大 200 |

条目统一为 `kind` `status` `actor` `caller_id` `callee_id` `skill_id` `trace_id` `ticket_jti` `summary` `detail` `created_at`。
