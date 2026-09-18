# SUNNY 策略门闩（P0）

| 项 | 内容 |
|----|------|
| 代码 | `sunny_registry/policy.py` |
| 决策 | [ADR-001](../decisions/ADR-001-开写前五件事.md) 发现≠访问；[ADR-002](../decisions/ADR-002-工作空间隔离.md) 升版旧票作废 |

控制面硬编码规则，不另起工作流引擎。管理员可越过对等门闩（出票、看私有卡）。

## 发现

| `x-sunny.discovery` | 对等搜索 / 列表 / 读卡 / 出票 | 管理员 | 创建者或本 Agent |
|----|------|--------|------------------|
| `registered_peers`（默认） | 可以 | 可以 | 可以 |
| `private` | 否（读卡 404） | 可以 | 可以 |
| `approval_required` | 同 private（P0 尚无审批流） | 可以 | 可以 |

下线 `disabled` 仍立刻退出对等可见。

## 技能

搜索只收 `side_effects=read` 且 `data_class` 为 `public` / `internal`。

对等出票拒绝：`write` / `execute_sql`、`data_class=restricted`、被调方不可被对等发现。管理员仍可代签。

## 票

载荷除 caller / callee / skill / TTL 外带 `card_version`（被调方当前 Card `version`）。验票时版本对不上或缺版本 → `401 ticket stale: card version changed`。
