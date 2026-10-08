# SUNNY 文档地图

按「现行决策 → 规格 → 立项调研」读，避免把调研当合同。

## 现行 · 工程与介绍

给人看的 HTML，可离线打开。运行中的 Registry 挂在匿名 `/help/`，不进 Hub 顶栏。合同仍是下面的 ADR / specs。

| 文档 | 用途 |
|------|------|
| [文档门户](./site/index.html) | 按管理者、用户、开发人员和集成方进入对应内容 |
| [项目介绍](./site/briefing.html) | 企业智能体孤岛、SUNNY 方案、角色价值、治理边界与路线图 |
| [工程说明](./site/engineering.html) | 架构 + 各模块参数、启动命令、成功判定、依赖 |
| [API 参考](./site/api.html) | 发现 / 登记 / 出票 / 管理 / MCP / sidecar |

## 现行

| 文档 | 用途 |
|------|------|
| [ADR-001 开写前五件事](./decisions/ADR-001-开写前五件事.md) | 对外技能、发现默认、调用票、示例租户 |
| [ADR-002 工作空间隔离](./decisions/ADR-002-工作空间隔离.md) | Agent 服务账号；不进个人 scratch |
| [ADR-003 Hub 角色权限](./decisions/ADR-003-Hub角色权限.md) | 管理员全权限；开发者看卡 + 维护自己发布的智能体 |
| [Card 规格](./specs/sunny-card.md) | JSON 字段、与 A2A / 资产卡的映射 |
| [Registry API](./specs/registry-api.md) | M1 注册 / 搜索 / 心跳 / 票 / 历史 |
| [策略门闩](./specs/policy.md) | 发现 / `data_class` / 副作用 / 票绑版本 |
| [观测](./specs/observe.md) | 搜索 / 出票 / 调用时间线，按 `trace_id` 对账 |
| [Join Packet 规格](./specs/join.md) | 监听 `0.0.0.0`、宣告局域网 URL、握手包 API |
| [MCP 发现面](./specs/mcp-discovery.md) | `POST /mcp` JSON-RPC + stdio；发现目录 / 能力 / 访问方式，不代调 |
| [Well-Known 拉取](./specs/well-known-pull.md) | 只交基址拉 Card；sidecar 已挂 well-known；`GET /agents/{id}/a2a` 剥企业字段 |
| [接入说明（给其他 Agent）](./join.md) | 可拷走的自注册手册；运行中以 `GET /api/v1/join.md` 为准 |
| [Adapter + Client](./specs/adapter.md) | M2 sidecar + P1 映射 / 槽校验 |
| [示例租户 lab.echo](./specs/lab-echo.md) | 回声 HTTP `:8092` + sidecar `:8093` |
| [Hub 手工 QA](./qa/hub-manual.md) | 管理台浏览器对照清单（登录 / 角色 / 各 hash 页） |

机器真源：

- Schema：[`../schemas/sunny-card.schema.json`](../schemas/sunny-card.schema.json)
- 样例：[`../cards/lab.echo.sample.json`](../cards/lab.echo.sample.json)

## 立项调研（已归档，决策以 ADR 为准）

| 文档 | 用途 |
|------|------|
| [可行性、需求、竞品与模块拆解](./research/SUNNY-AgentHub-可行性与前期需求.md) | 选型 B、模块切分、M0–M5 |
| [定位：多 Agent 栈里站在哪](./research/多Agent协作-行业口径与现网对照.md) | 同机编排与跨运行时目录分层；发现 ≠ 访问 |
| [注册机制对具身协作的启发](./research/注册机制-跨户与户内协作.md) | 跨户同类型策略群、户内不同设备直连；可抽象的建设原则 |
| [同类项目对照](./research/同类项目对照.md) | 竞品与可借鉴点：控制面近亲、数据面、编排层；学什么、不抄什么 |
| [Well-Known 拉取（一周计划，已落地）](./plans/week-well-known-pull.md) | S0 只交基址拉 Card |
| [审批流（一周计划，已落地）](./plans/week-approval-flow.md) | `approval_required` 真审批 |
| [弃用 + 升版变更流](./plans/week-deprecated-subscribe.md) | `deprecated` 能读不能出新票；`card-changes` 拉取 |
| [协作范围 scope](./plans/week-collab-scope.md) | 可选 `household` / `cohort`；不写则保持已登记对等可见 |

## 还没做（刻意）

- 不把 Registry 当调用网关
- 不做公司 SSO、不做外置 agentgateway
- 不收官方 MCP 商店或 Prompt 仓
