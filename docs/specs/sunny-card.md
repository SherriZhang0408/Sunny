# SUNNY Agent Card 规格（v0.1）

| 项 | 内容 |
|----|------|
| 状态 | 草案，已有无密钥样例 |
| Schema | [`../../schemas/sunny-card.schema.json`](../../schemas/sunny-card.schema.json) |
| 样例 | [`../../cards/aidata.hermes.sample.json`](../../cards/aidata.hermes.sample.json) |
| 决策 | [ADR-001](../decisions/ADR-001-开写前五件事.md) |

> 对内这一份 JSON 是真源。以后导出 `/.well-known/agent-card.json` 时，剥掉 `x-sunny` 即可对齐 A2A v1.0。  
> **未完成样例评审前，不建库、不写管理台。**

---

## 1. 和 A2A、现网资产卡的关系

```text
现网资产卡 YAML / Skill 契约
        │ 人审圈选对外技能
        ▼
   SUNNY Card（本规格）
        │ 登记后被已登记对等发现
        ▼
   sidecar invoke（票 + 槽）──► 包装器 / Guard
```

| 来源 | 管什么 | Card 怎么用 |
|------|--------|-------------|
| [A2A v1.0 AgentCard](https://a2a-protocol.org/v1.0.0/specification/) | `name` `description` `version` `supportedInterfaces` `capabilities` `defaultInputModes` `defaultOutputModes` `skills[]` | 顶层原样收录 |
| 语义资产卡 `skills/assets/*.yaml` | 意图、边界、权限、版本 | 映射到 `skills[].x-sunny.source_asset` |
| Skill JSON 契约 | 输入 / 输出槽 | 映射到 `skills[].x-sunny.input_schema` / `output_schema` |
| SUNNY 企业扩展 | 工作空间、发现、副作用、禁挂清单 | 全部放 `x-sunny`，避免污染 A2A 导出 |

资产卡仍是说明书；**Card 才是跨运行时发现面**。不要把内部 6 张资产卡原样抄成 6 个对外 skill。

---

## 2. 必填与禁填

**卡级必填**

- A2A：`name` `description` `version` `supportedInterfaces`（≥1）`capabilities` `defaultInputModes` `defaultOutputModes` `skills`（≥1）
- SUNNY：`x-sunny.agent_id` `x-sunny.workspace` `x-sunny.discovery` `x-sunny.access_tier` `x-sunny.not_exposed` `x-sunny.invoke_identity` `x-sunny.scratch_access`

**技能级必填**

- A2A：`id` `name` `description` `tags`（≥1）
- SUNNY：`x-sunny.data_class` `x-sunny.side_effects` `x-sunny.input_schema` `x-sunny.output_schema`

**整卡禁止出现**

- 字段名或字符串值里的 token / password / secret / api_key / authorization / 连接串 / 私钥
- 真实内网主机名（样例只用 `*.internal.example`）
- `side_effects` 为 `write` 或 `execute_sql` 却把 `data_class` 标成 `public`

接入规则（将来校验器，现在脚本已做）：缺 skill、缺接口、含密钥 → 拒绝。

---

## 3. `x-sunny` 字段

### 3.1 卡级

| 字段 | 取值 | 说明 |
|------|------|------|
| `agent_id` | `aidata.hermes` | 稳定主键，点号分段 |
| `workspace` | 非空字符串 | 服务工作区标签；P0 不分三级（ADR-002） |
| `discovery` | `registered_peers` / `private` / `approval_required` | 默认 `registered_peers`（ADR-001 §3） |
| `access_tier` | `S0` / `S1` / `S2` | 纯登记 / sidecar / 原生 A2A |
| `lifecycle` | `draft` / `registered` / `disabled` | 样例内容已评审，尚未挂进 Registry |
| `not_exposed` | 字符串数组 | 内部有、对外禁挂的 skill 或能力 |
| `source_assets` | 资产卡 ID 列表 | 追溯用 |
| `invoke_auth` | `sunny_ticket` | P0 短时票（ADR-001 §4） |
| `invoke_identity` | `agent_service` | 只认 Agent 服务账号（ADR-002） |
| `scratch_access` | `none` | 跨 Agent 不进个人 scratch |
| `notes` | 字符串 | 人读的未决事项，不进搜索 |

### 3.2 技能级

| 字段 | 取值 | 说明 |
|------|------|------|
| `data_class` | `public` / `internal` / `restricted` | 公开目录 / 已登记对等 / 需 Extended Card |
| `side_effects` | `read` / `write` / `execute_sql` | `write` / `execute_sql` 默认不进跨 Agent 搜索，除非策略白名单 |
| `source_asset` / `source_skill` | 现网 ID | 从哪张资产卡收窄而来 |
| `invoke.method` / `invoke.path` | HTTP | sidecar 对外路径，不是业务真源 URL |
| `input_schema` / `output_schema` | JSON Schema | 调用方填槽、校验回包 |
| `when_not_to_use` | 字符串数组 | 避免模型乱路由 |

---

## 4. 数据智能体首张名片怎么从资产卡收窄

依据 ADR-001，只对外 2 个 skill。对照现网：

| 对外 skill | 收窄自 | 关键收窄 |
|------------|--------|----------|
| `collect.strategy.query` | `KB.API.Retrieve.v1` / `kb.retrieve` | 检索域锁在采集策略枚举与 `ai_collect` 字典，不开放整库知识 |
| `collect.volume.query` | `ES.API.QueryAiCollect.v1` / `es.query_ai_collect` | 只保留 count；去掉 compose 给建任务用的 DSL、preview 出图、`--confirm` 变成人审建任务的跳板 |

接口占位：

```text
POST https://aidata.internal.example/sunny/v1/invoke
protocolBinding: HTTP+JSON
Authorization: Bearer <Registry 短时票>
```

真源仍读 `AIDATA_*` 环境变量，**不进 Card、不进 Git。**

---

## 5. 调用方最小请求

```json
{
  "skill_id": "collect.volume.query",
  "slots": {
    "mission_name": "living_room",
    "quest_name": "MetaData",
    "robotType": ["0gxgac"]
  },
  "trace_id": "caller-trace-…"
}
```

成功回包必须能对上 `trace_id`，并带 `ready` / `mock`。`ready=false` 时调用方不得把数字当业务余量。

---

## 6. 校验

```bash
python3 scripts/validate_card.py cards/aidata.hermes.sample.json
```

通过标准：Schema 合法、至少 1 个 skill 与 1 个接口、树里无密钥痕迹。
