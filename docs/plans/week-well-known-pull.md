# 一周计划：Well-Known 拉取登记

| 项 | 内容 |
|----|------|
| 窗口 | 约 5 个工作日，单开，不与审批流并行抢同一套登记 API |
| 状态 | 已落地（2026-09-20） |
| 学自 | [prassanna-ravishankar/a2a-registry](https://github.com/prassanna-ravishankar/a2a-registry) `POST /agents/register { wellKnownURI }` |
| 上游 | [同类项目对照](../research/同类项目对照.md) §1.4 |
| 红线 | 拉卡后仍走现有 schema / 密钥门闩；不信任公网 Card；Registry 不代发业务 |

## 目标

同事只给一个基址。Hub 去拉 `/.well-known/agent-card.json`（或对方声明的 Card URL），校验后按 S0 登记。周期重抓，Card 变了升版本、旧票作废。

## 验收

- `POST /api/v1/agents/pull`（管理员或持 enroll 的自注册）：body `{ "url": "http://host:8091" }`。
- 解析顺序：`{url}/.well-known/agent-card.json` → `{url}/.well-known/agent.json` → 若 url 本身已是 json 则直接 GET。
- 拉到的 JSON 必须过 `validate_card`；含密钥字段直接拒。
- 已存在的 `agent_id`：仅管理员或本 Agent 可刷新；升 `version` 则旧票 stale。
- 后台或手动 `POST /agents/{id}/refresh` 重抓；失败保留旧卡并记探活/观测。
- Join Packet 补一节「只交基址」。
- pytest：假 HTTP 服务出合法卡 / 非法卡 / 超时；禁止 `file://` 与云 metadata。

## 日程

| 日 | 任务 | 复杂度 |
|----|------|--------|
| D1 | 规格：`docs/specs/well-known-pull.md`；SSRF 规则与探活模块复用 | S |
| D2 | `POST /agents/pull` + 解析顺序 + 入库 | M |
| D3 | `POST /agents/{id}/refresh`；升版作废旧票 | M |
| D4 | Hub「从 URL 登记」表单；Join Packet 一节 | S |
| D5 | 测试与手工 QA；不接审批流 | S |

## 会改的文件

- `sunny_registry/probe.py`（复用 URL 白名单）
- `sunny_registry/app.py`、`store.py`、`join.py`
- `web/assets/app.js`（发布页）
- `tests/test_pull.py`、`docs/specs/registry-api.md`、`docs/join.md`

## 风险

- 内网 SSRF：只允许 http(s)，跟跳转，拒 169.254.169.254 / 元数据主机。
- 对方 Card 缺 `x-sunny.agent_id`：允许管理员在 pull 时补，或拒并提示用 Hub 表单。
- 不要做成公网爬虫。
