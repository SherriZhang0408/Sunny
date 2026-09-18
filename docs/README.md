# SUNNY 文档地图

按「现行决策 → 规格 → 立项调研」读，避免把调研当合同。

## 现行

| 文档 | 用途 |
|------|------|
| [ADR-001 开写前五件事](./decisions/ADR-001-开写前五件事.md) | 对外技能、发现默认、调用票、ChatBI 三档 |
| [ADR-002 工作空间隔离](./decisions/ADR-002-工作空间隔离.md) | Agent 服务账号；不进个人 scratch |
| [ADR-003 Hub 角色权限](./decisions/ADR-003-Hub角色权限.md) | 管理员全权限；开发者看卡 + 维护自己发布的智能体 |
| [Card 规格](./specs/sunny-card.md) | JSON 字段、与 A2A / 资产卡的映射 |
| [Registry API](./specs/registry-api.md) | M1 注册 / 搜索 / 心跳 / 票 / 历史 |
| [Join Packet 规格](./specs/join.md) | 监听 `0.0.0.0`、宣告局域网 URL、握手包 API |
| [接入说明（给其他 Agent）](./join.md) | 可拷走的自注册手册；运行中以 `GET /api/v1/join.md` 为准 |
| [Adapter + Client](./specs/adapter.md) | M2 sidecar 验票、两技能、另一进程调用 |
| [ChatBI 技能契约](./specs/chatbi-skill-contract.md) | 意向草稿；**八字段表搁置** |

机器真源：

- Schema：[`../schemas/sunny-card.schema.json`](../schemas/sunny-card.schema.json)
- 样例：[`../cards/aidata.hermes.sample.json`](../cards/aidata.hermes.sample.json)

## 立项调研（已归档，决策以 ADR 为准）

| 文档 | 用途 |
|------|------|
| [可行性、需求、竞品与模块拆解](./research/SUNNY-AgentHub-可行性与前期需求.md) | 选型 B、模块切分、M0–M5 |
| [多 Agent 行业口径与现网对照](./research/多Agent协作-行业口径与现网对照.md) | 同机/跨机、发现≠访问 |
| [接入 ChatBI 的条件](./research/AI数据智能体接入ChatBI-条件.md) | 三档接入、禁止整段转发 |

## 还没做（刻意）

- 不催填 ChatBI 八字段；不把 Registry 当调用网关
- 不改 Hermes 内核；余量查询接现网 AIDATA 包装器仍可选
- ChatBI 第二户（M3）
