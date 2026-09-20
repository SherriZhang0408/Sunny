# 一周计划：approval_required 真审批

| 项 | 内容 |
|----|------|
| 窗口 | 约 5 个工作日，单开；建议排在 Well-Known 拉取之后 |
| 学自 | mcp-gateway-registry 准入闸；Nacos 控制台人审 |
| 上游 | [同类项目对照](../research/同类项目对照.md)；[policy.md](../specs/policy.md) |
| 现状 | 已落地（2026-09-20）：`pending` / `approved` / `rejected` |
| 规格 | [`../specs/policy.md`](../specs/policy.md) |

## 目标

开发者或自注册可以挂「待审批」卡。管理员通过后变成 `registered_peers`（或保持审批通过后的可见档）。拒绝则保持不可见并记原因。不要做成通用工作流引擎。

## 验收

- 登记时可写 `x-sunny.discovery=approval_required`；Hub 发布可选「需审批后可见」。
- 对等：待审批卡不进 `/search`、列表、出票（现有门闩保持）。
- 管理员：`GET /api/v1/approvals` 待办；`POST /agents/{id}/approve` → `registered_peers`；`POST /agents/{id}/reject` 带原因，仍不可见。
- 观测：`card` 事件记 approve / reject。
- 开发者能看见自己的待审批卡并改说明，不能自己通过。
- 管理台「待审批」分段；pytest 覆盖对等不可见、管理员通过后可搜（仍要在线心跳）。

## 日程

| 日 | 任务 | 复杂度 |
|----|------|--------|
| D1 | 规格补 `docs/specs/policy.md`：状态机 draft/pending/approved/rejected | S |
| D2 | `approve` / `reject` API；`approvals` 列表 | M |
| D3 | Hub 待办与详情按钮；开发者只读自己的待审卡 | M |
| D4 | 观测 + Join Packet「上架要人审」一句 | S |
| D5 | 测试；确认 Well-Known pull 进来的卡也能标待审 | S |

## 会改的文件

- `sunny_registry/policy.py`、`store.py`、`app.py`、`observe.py`
- `web/assets/app.js`、`app.css`（待审批分段）
- `tests/test_policy.py`、新 `tests/test_approval.py`
- `docs/specs/policy.md`、`registry-api.md`、`qa/hub-manual.md`

## 风险

- 不要引入审批引擎或多人会签。P0 只有管理员过 / 拒。
- 通过后旧票：若 Card `version` 没变，票仍有效；若审批同时改了对外技能，应升版本。
- 与「已登记默认可互发现」（ADR-001 §3）的关系：默认仍是 `registered_peers`；`approval_required` 是可选更严档，不是新默认。
