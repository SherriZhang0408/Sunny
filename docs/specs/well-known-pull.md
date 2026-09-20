# Well-Known 拉取登记

| 项 | 内容 |
|----|------|
| 状态 | 已落地 |
| 代码 | `sunny_registry/pull.py`、`store.pull_from_url` / `refresh_from_source` |
| 计划 | [`../plans/week-well-known-pull.md`](../plans/week-well-known-pull.md) |
| 学自 | a2a-registry `register-by-URI`；企业内网不信任公网 Card |

同事只给基址。Registry **去拉** SUNNY Card，仍走 `validate_card`（schema + 禁密钥）。不代发业务，不跟未知跳转到 metadata。

## 解析顺序

输入 `url`（http/https，无账号密码，主机不得为 `0.0.0.0` / 链路本地 / 云 metadata）：

1. 若 path 已是 `/.well-known/agent-card.json`、`/.well-known/agent.json` 或以 `.json` 结尾 → 只 GET 这一条。
2. 否则依次：`{url}/.well-known/agent-card.json` → `{origin}/.well-known/agent-card.json` → 同路径的 `agent.json`。
3. 仅 `200` 且 body 是 JSON 对象算成功。跳转最多 3 次，每跳再验主机。体积上限 256KiB。
4. User-Agent：`SUNNY-Registry-Pull/1.0`。

缺 `x-sunny.agent_id`：管理员可在 body 里补 `agent_id`；否则 `400`，请改用 Hub 表单贴 JSON。

## API

| 方法 | 路径 | 谁 | 说明 |
|------|------|----|------|
| POST | `/api/v1/agents/pull` | Hub 用户，或 `X-Sunny-Enroll` 自注册 | body `{url, enrollment_source?, agent_id?}`。新卡发 `sak_`；已存在则刷新（不重发 key） |
| POST | `/api/v1/agents/{id}/refresh` | 管理员、创建者或本 Agent | 用库里的 `card_source_url` 重抓。失败**保留旧卡** |

已存在的 `agent_id`：仅管理员、创建该卡的开发者、或本 Agent key 可刷新。持 enroll 的匿名不能覆盖别人的卡（`409`）。

升 `version` 后旧调用票作废（既有 `card_version` 门闩）。

## 环境变量

| 名 | 默认 | 用途 |
|----|------|------|
| `SUNNY_PULL_TIMEOUT_S` | `5` | 单次 GET 超时 |

库字段 `agents.card_source_url` 记下成功拉到的那条 URL，供 refresh。

## 对向：本仓怎么挂出去

| 谁 | 路径 | 内容 |
|----|------|------|
| sidecar | `/.well-known/agent-card.json` · `/.well-known/agent.json` · `/sunny/v1/card` | 完整 SUNNY Card，含 `x-sunny` |
| Registry | `GET /api/v1/agents/{id}/a2a` | 剥掉 `x-sunny` 与 restricted 技能的 A2A Card |

两路都带 `ETag`（Card `version`）。

## 周期扫

Registry 进程内定时器（`SUNNY_SWEEP_S`，默认 60 秒；`0` 关闭）。每轮：

1. 对所有 `lifecycle=registered` 的卡做探活（不代发 skill）。
2. 有 `card_source_url` 且距上次刷新超过 `SUNNY_REFRESH_INTERVAL_S`（默认 300 秒）的，再 `refresh`。失败**保留旧卡**。

探活失败分类写入 `probe.category`：`OK` / `TIMEOUT` / `TLS` / `BLOCKED` / `404` / `HTTP` / `UNREACHABLE` / `NO_INTERFACE`。  
无心跳但最近探活成功 → `runtime_status=online`（S0 可被搜索）。最近探活失败且心跳也不新鲜 → `unreachable`，搜索默认排除。管理员 `alive=0` 仍能看见。

Actor：`system:sweep`。`GET /api/v1/health` 的 `sweep.last` 记上一轮计数。
