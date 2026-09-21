# SUNNY 文档地图

按「现行决策 → 规格 → 立项调研」读，避免把调研当合同。

## 现行 · 工程与汇报

给人看的 HTML，可离线打开。合同仍是下面的 ADR / specs。这次不进 Hub 顶栏；以后可挂 Registry `/help`，或拷进 `web/help/`。

| 文档 | 用途 |
|------|------|
| [文档门户](./site/index.html) | 三份入口，以及和 specs 的分工 |
| [工程说明](./site/engineering.html) | 各模块参数、启动命令、成功判定、依赖 |
| [API](./site/api.html) | 发现 / 登记 / 出票 / 管理 / MCP / sidecar |
| [对外汇报演示](./site/briefing.html) | 混合场约 12 页幻灯；键盘左右翻页 |

## 现行

| 文档 | 用途 |
|------|------|
| [ADR-001 开写前五件事](./decisions/ADR-001-开写前五件事.md) | 对外技能、发现默认、调用票、ChatBI 三档 |
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
| [第二户 lab.echo](./specs/lab-echo.md) | 回声 HTTP `:8092` + sidecar `:8093` |
| [Hermes discover / invoke](./specs/hermes-skills.md) | 可选 Skill，默认关；不改内核 |
| [Hub 手工 QA](./qa/hub-manual.md) | 管理台浏览器对照清单（登录 / 角色 / 各 hash 页） |
| [ChatBI 技能契约](./specs/chatbi-skill-contract.md) | 意向草稿；**八字段表搁置** |

机器真源：

- Schema：[`../schemas/sunny-card.schema.json`](../schemas/sunny-card.schema.json)
- 样例：[`../cards/aidata.hermes.sample.json`](../cards/aidata.hermes.sample.json)

## 立项调研（已归档，决策以 ADR 为准）

| 文档 | 用途 |
|------|------|
| [可行性、需求、竞品与模块拆解](./research/SUNNY-AgentHub-可行性与前期需求.md) | 选型 B、模块切分、M0–M5 |
| [多 Agent 行业口径与现网对照](./research/多Agent协作-行业口径与现网对照.md) | 同机/跨机、发现≠访问 |
| [同类项目对照](./research/同类项目对照.md) | 控制面近亲、可借鉴点（开源仓 / 规格 / 厂商文档）；交互画布只在 Cursor canvases，不进仓 |
| [Well-Known 拉取（一周计划，已落地）](./plans/week-well-known-pull.md) | S0 只交基址拉 Card |
| [审批流（一周计划，已落地）](./plans/week-approval-flow.md) | `approval_required` 真审批 |
| [弃用 + 升版变更流](./plans/week-deprecated-subscribe.md) | `deprecated` 能读不能出新票；`card-changes` 拉取 |
| [接入 ChatBI 的条件](./research/AI数据智能体接入ChatBI-条件.md) | 三档接入、禁止整段转发 |

## 还没做（刻意）

- 不催填 ChatBI 八字段；不把 Registry 当调用网关
- 不改 Hermes 内核；余量查询接现网 AIDATA 包装器仍可选
- ChatBI 第二户（M3）；本仓第二户已是 `lab.echo`
- 图像 / 闭环 Chat 路由不经 SUNNY（`sunny.invoke` 会拒）
