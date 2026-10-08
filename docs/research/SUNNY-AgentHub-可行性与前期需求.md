# SUNNY AgentHub：可行性、需求、竞品与模块拆解

> **归档说明（2026-09-18）：** 立项调研。现行决策以 [`../decisions/ADR-001-开写前五件事.md`](../decisions/ADR-001-开写前五件事.md) 为准；Card 真源是 [`../../schemas/sunny-card.schema.json`](../../schemas/sunny-card.schema.json)。

| 项 | 内容 |
|----|------|
| 日期 | 2026-09-18 |
| 性质 | 立项前调研（需求整理 + 竞品 + 工程拆解，不是实现规格） |
| 检索 | AnySearch `api.anysearch.com` 当日不可达；改用公开网页交叉核对（A2A 规范、云厂商文档、开源仓库） |
| 首批接入 | 已有 HTTP 的业务 Agent；本仓示例是 `lab.echo` |

> 一句话：  
> **可行，而且现在就该做——但 SUNNY 一期只做「企业内策展型注册中心 + 薄适配器」，不要做公网 Agent 市场，也不要逼业务 Agent 改造成完整 A2A。**  
> 名片对齐 A2A Agent Card；调用默认走对方已有 HTTP。发现和访问必须分开。

命名：SUNNY 取自电影 *I, Robot* 里的机器人桑尼——不是又一个只会执行三定律的机体，而是能在规则下选择协作的那一个。产品隐喻也成立：Hub 不替代各 Agent 的决策，只让异构智能体按名片互相找到、按策略互相调用。

---

## 0. 问题怎么框

企业里已经有多个能独立决策的智能体，HTTP 也能打通。痛点不是调不通，而是：

1. **每次对接都是点对点**：基址、鉴权、槽位、失败语义写死在调用方。
2. **对方一换接口，调用方全改**；新 Agent 进来没有标准「怎么介绍自己」。
3. **能力在对方脑子里，不在目录里**：调用方不知道对方有哪些已批准技能。
4. **你希望别人改动尽量小**：同事不会为了接入把业务进程重写成 A2A Server。

所以 SUNNY 要解决的是 **控制面**（谁在、会什么、谁看得见、版本与心跳），不是再造一套对话运行时。

成功标准（前期可验收）：

| 标准 | 过线 |
|------|------|
| 首批接入 | 业务 Agent 用 sidecar 挂上名片，**不改业务内核** |
| 发现 | 另一个进程能按 skill / tag 查到它，拿到调用入口 |
| 低改动 | 现有 HTTP Agent 只加一份 Card JSON + 可选 sidecar，不重写业务 |
| 安全 | 看见名片 ≠ 能调用；技能级授权；不把密钥写进 Card |
| 边界 | 不替代对方的鉴权、数据权限和业务执行 |

---

## 1. 可行性判断

### 1.1 结论：做「小而准」可行；做「行业总注册表」不可行

| 命题 | 判断 | 依据 |
|------|------|------|
| 企业内需要 Agent 目录 | **强需求** | A2A 把 Agent Card 标准化了，但 **明确不规定注册表 API**（[Agent Discovery](https://a2a-protocol.org/v1.0.0/topics/agent-discovery/)）。云厂商 2026 年把 Registry 当成控制面战场（AWS / Google / Microsoft / MuleSoft 都已有目录）。 |
| 用名片做发现 | **对** | Card 就是「数字名片」：身份、技能、入口、鉴权方案。v1.0 必填：`name` `description` `version` `supportedInterfaces` `capabilities` `defaultInputModes` `defaultOutputModes` `skills[]`。 |
| 必须先上完整 A2A 线协议 | **否** | Google Cloud Agent Registry 同时收 `A2A_AGENT_CARD` 和 `NO_SPEC` REST。业界已经承认：先登记入口，再逐步讲 A2A。 |
| 必须自建调用网关 | **一期不必** | 注册表返回 Card；调用仍打到 Agent 自己的 URL。网关是数据面（审计、限流），和目录是两件事。agentgateway 这类项目证明二者可拆。 |
| 接入必须大改业务 Agent | **否，这是风险点也是设计点** | 薄适配器 / sidecar：对外出 Card + REST invoke，对内转现有 HTTP。业务进程保持原样。 |
| 做成公网市场 | **不做** | a2a-registry.org、AgoraHub 面向公网发现与「Meta Agent 路由」。公司内网要的是策展、审批、隔离，不是 DNS 验证上架。 |
| 和现网合同冲突吗 | **不冲突，若边界守住** | SUNNY 只让「已批准的技能」被发现；执行权仍在各 Agent。 |

行业里一句必须留下的话（A2A 官方 + Microsoft 同构）：

> **Discovery before access.** 注册表回答「谁在这里、会什么」；授权回答「这次能不能调」。Card 里不要塞静态密钥。

### 1.2 和你昨天两份备忘的关系

| 昨天的判断 | 今天怎么用 |
|------------|------------|
| 多 Agent 是逻辑关系，主路径可以仍在各自运行时 | SUNNY **不拆** 对方内部子代理；它管的是 **跨运行时** |
| 出现第二套 Agent 时再评估 | 评估结果是 **先做目录，后做 A2A 线协议** |
| 接入要显式 action / 槽 / 不整段转发 | 写进 Card 的 `skills[]`，而不是只写一句「我会聊天」 |
| 发现 ≠ 访问 | SUNNY 的第一原则 |

### 1.3 主要风险（先写，避免后半段膨胀）

1. **目录变成第二个编排器**：模型在 SUNNY 里「随便找个 Agent 聊聊」。必须按 skill id 调用，禁止无 skill 的自由对话作为默认路径。
2. **Card 写得太虚**：`description` 很长、`skills` 只有一条「通用问答」→ 发现废了。技能必须对应可测的入口（模板 ID、包装器、action）。
3. **借 Hub 提权**：调用方没有某项数据权限，却通过「发现了对方」去执行写操作或查询。策略层要能拒绝。
4. **协议版本坑**：A2A v1.0 把顶层 `url` 收进 `supportedInterfaces[]`；不少实现还停在 0.3。SUNNY 对内用一份规范 Card，对外兼容两代字段。
5. **范围膨胀**：联邦 DHT（AGNTCY）、Agent 365 式身份治理、公网收录，都不是 P0。

---

## 2. 前期需求整理

### 2.1 用户与场景

| 角色 | 要什么 |
|------|--------|
| 调用方 Agent | 按技能发现对方的 **已批准技能**，按槽调用，自己的业务流程留在原处 |
| 被调方 Agent | 尽量不改业务进程；最多加 Card + sidecar |
| 未来 Agent 主人 | 一份 YAML/JSON + 心跳，就能上架；审批通过才被搜到 |
| 平台值守 | 看到谁在线、谁调了谁、哪张 Card 过期、哪个技能被禁用 |
| 安全 / 合规 | 工作空间隔离；敏感技能只给认证后的 Extended Card |

优先场景（P0 只做前两条）：

1. **登记**：一个 Agent 上架 1–3 个已契约化的技能。
2. **发现**：本机另一个 client 按 skill / tag 查到 Card。
3. **调用（P0.5）**：client 按 skill id 打到 sidecar，sidecar 转对方已有 HTTP；回 `trace_id`。
4. **第二 Agent**：再挂一个独立进程（本仓后来用 `lab.echo`），调用方发现并调用。
5. **拒绝路径**：未授权 skill、无身份、对方拒绝 → 调用方降级，不自动改道去执行写操作。

非目标（写进 Charter 红线）：

- 不替代对方的对话循环和业务编排
- 不做公网收录、不做加密货币 / x402 结算
- 不把 MCP 工具目录和 Agent 目录混成一张无类型表（可并存，类型必须分开）

### 2.2 功能需求（按 MoSCoW）

**Must**

- Agent Card 的创建、更新、下线、按 `agent_id` 读取
- 按 `skill.id` / `tags` / `workspace` 搜索
- 心跳与状态（`online` / `stale` / `disabled`）
- 接入规则：校验 Card schema；缺 skill / 缺接口 / 密钥字段直接拒绝
- 工作空间 + 审批：~~默认「登记了只对自己可见，审批后才进搜索」~~ **已改（ADR-001）：已登记 Agent 默认可互发现；调用仍要短时票**
- 调用鉴权与目录鉴权分离（至少：注册用管理员 Token，调用用 audience 绑定的短 Token）
- Python sidecar：把已有 REST 映射成 Card + invoke
- 审计：谁在何时发现了谁、调用了哪个 skill、对方 `trace_id`

**Should**

- Extended Card：登录后才看到内网 URL / 敏感技能
- 与 A2A v1.0 字段对齐，可选导出 `/.well-known/agent-card.json`
- 技能级 input schema（JSON Schema），便于调用方填槽
- 管理台：列表、审批、禁用、看心跳

**Could**

- 完整 A2A `SendMessage` / Task 生命周期
- 数据面网关（限流、统一审计、mTLS 终结）
- MCP Bridge：把已批准 Agent 技能暴露成 MCP tool（AgoraHub 同款，二期）
- 语义检索 Card（向量搜「谁会做某类事」）

**Won't（一期）**

- DNS-SD / 全网广播
- AGNTCY DHT 联邦
- 自动编排「找一个最合适的 Agent 把任务做完」（那是 Meta Agent，不是 Hub）

### 2.3 接入规则（别人怎么「便捷」进来）

目标：**改业务代码趋近于 0**。三种接入档，SUNNY 都收，但搜索权重不同。

| 档 | 对方要做什么 | SUNNY 怎么对待 | 适合谁 |
|----|--------------|----------------|--------|
| **S0 纯登记** | 交一份 Card JSON（可手写），填 `supportedInterfaces` 为现有 REST | 可发现；调用方按 Card 里的 REST 自己调 | 最懒的同事；Google 的 `NO_SPEC` |
| **S1 sidecar** | 不改业务；旁边跑 `sunny-adapter`，读映射文件 | 对外统一 invoke；对内转 HTTP | **默认推荐** |
| **S2 原生 A2A** | 自己实现 Card + JSON-RPC | 原样收录 | 将来新写的 Agent |

S1 映射文件（示意，不是最终 schema）：

```yaml
agent_id: lab.echo
card: ./cards/lab.echo.sample.json
routes:
  - skill_id: echo.ping
    method: POST
    url: ${ECHO_URL}/v1/echo
    map:
      q: $.slots.query
heartbeat:
  url: ${ECHO_URL}/health
  interval_s: 30
```

「基于某些规则接入」建议做成 **校验器而不是工作流引擎**：

1. Card 能通过 schema（必填字段、skill 至少 1 条、接口至少 1 个）
2. 健康检查通过才标 `online`
3. 每个 skill 声明 `data_class`（`public` / `internal` / `restricted`）和 `side_effects`（`read` / `write` / `execute_sql`）
4. `execute_sql` / `write` 默认不进跨 Agent 搜索，除非策略白名单
5. 禁止 Card 内出现 token、密码、连接串

首张名片建议 **只暴露已契约化的技能**，不要把整个对话入口挂上去。

---

## 3. 竞品分析

检索说明：AnySearch 不可达。下列对照来自 A2A 官方、Google Cloud / Microsoft / Nacos 文档、Forbes / Atlan 2026 综述，以及 AGNTCY、agentgateway、a2a-registry.org、AgoraHub、Spring AI Alibaba、BeeAI 公开页。

### 3.1 地图：四类东西不要混

```text
协议      A2A = Agent 名片 + 任务委托     MCP = 工具/数据源
控制面    Registry / Directory            谁在、会什么、版本、可见性
数据面    Gateway / Proxy                 真正转发调用、鉴权、限流、观测
身份面    Entra Agent ID 等               每个 Agent 是一个身份，不是一张网页账号
```

SUNNY 一期站在 **控制面**，用 sidecar 轻轻碰数据面。不要一上来四层都自研。

### 3.2 对照表

| 产品 | 定位 | 对 SUNNY 的启示 | 不要学 |
|------|------|-----------------|--------|
| **A2A 规范本身** | 名片 + 发现策略三种（Well-Known / 策展目录 / 直连配置）；**不规定 Registry API** | Card 字段对齐规范；Hub 的 API 我们可以自己定 | 以为实现了 Card 就等于实现了 A2A 全家桶 |
| **Google Cloud Agent Registry** | GCP 内目录；收 A2A **和** 普通 REST；技能可检索；发现与 IAM 分离 | **S0 REST 准入是正确的**；跨项目要手登记 | 绑死 GCP；自动跨项目发现 |
| **Microsoft Agent 365 / Entra Registry** | Agent 当身份；清单、风险、Graph API；发现前做策略 | 工作空间 + 审批；Extended Card | 重做一套企业 IAM |
| **AWS Agent Registry** | Bedrock AgentCore 内目录；关键词 + 语义搜 | 二期可以加语义搜 | AWS 锁 |
| **Nacos 3.x AI Registry** | AgentCard + MCP + Skill + Prompt 分资源；Spring AI Alibaba 自动注册 | 资源要分类型；注册 / 发现开关可拆 | 把 Nacos 整包搬进 Python 仓当第一依赖 |
| **AGNTCY dir / ADS** | 联邦、OCI、DHT、OASF；Linux Foundation | 知道「目录可以联邦」即可 | P0 上 DHT |
| **agentgateway（Solo.io → LF）** | MCP/A2A **代理**，不是目录 | 以后若要统一审计，可考虑前置，不必自研代理 | 用网关冒充注册中心 |
| **a2a-registry.org** | 公网目录；登记处自己也是一个 A2A Agent；`/a2a/discover` | 「Hub 自己也可以有一张 Card」好玩，可做演示 | 公网默认可见、DNS 验证上架 |
| **AgoraHub** | A2A 目录 + MCP Bridge + 信任分 | MCP Bridge 可列为 Could | 信任分、公开匹配算法当主路径 |
| **Spring AI Alibaba A2A** | ReactAgent 自动出 Card，注册 Nacos，再 `A2aRemoteAgent` | 自动导出对 Java 友好；我们要对 **已有 HTTP** 友好 | 绑定 Spring Bean |
| **BeeAI** | ACP 已并入 A2A；用 adapter 包一层 | 印证「适配器比改内核便宜」 | 再引入一套 ACP |
| **业务仓已有目录** | 任务表、算子目录、技能说明 | **领域目录继续留在业务仓**；SUNNY 不取代它们 | 把业务任务目录搬进 Hub |

### 3.3 差异化（SUNNY 为什么还值得做）

云厂商目录进不了企业内网里已经在跑的 HTTP Agent。Nacos 能做，但默认叙事是 Java 微服务 + 再挂一层 AI 资源。  
SUNNY 的切口更窄：

1. **先收「已经在跑的 HTTP Agent」**，A2A 是可选升级。
2. **技能必须带槽和副作用声明**，挡整段转发和借路执行。
3. **用本仓 `lab.echo` 做跨进程验收**，不把某个业务系统写成产品前提。
4. **企业内网、工作空间、人审上架**，不做公网 Meta Agent。

### 3.4 架构选项（选一条，避免并行三套）

| 选项 | 做法 | 复杂度 | 优点 | 缺点 |
|------|------|--------|------|------|
| A. 只写文档目录 | Markdown 列表 | S | 零开发 | 解决不了发现与鉴权 |
| B. **策展 Registry + Sidecar** | 自研小服务 + 映射文件 | M | 改动小、对齐现网红线 | 要自己养服务 |
| C. 直接上 Nacos AI Registry | 部署 Nacos 3 + Java/SDK | M–L | 现成注册发现 | 栈不匹配、REST 包装仍要自己写 |
| D. Registry + 完整 A2A + agentgateway | 目录 + 线协议 + 代理 | L | 最「标准」 | 首批 Agent 都要大改；周期翻倍 |
| E. 挂到公网 A2A Registry | 外网上架 | S | 演示快 | 错误的信任域 |

**最实际：B。**  
**最大胆但仍合理：B 的数据面以后接 agentgateway，而不是自研代理。**

---

## 4. 目标架构（B 方案）

```text
                    ┌──────────────────────────┐
                    │     SUNNY Registry        │
                    │  Card · 搜索 · 心跳 · 审批 │
                    │  策略：谁能看见 / 谁能调   │
                    └────────────┬─────────────┘
                                 │ 只返回 Card + 短期调用票
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
   sunny-adapter           sunny-adapter            原生 A2A
   (调用方或被调方)        (lab.echo)               (未来)
          │                      │
          ▼                      ▼
   对方已有 HTTP           回声 HTTP
   本地 handler            显式槽
```

调用链（推荐）：

```text
调用方 Agent
  → SUNNY Search(skill=echo.ping)
  → 得到 Card + invoke_url + 调用票
  → 打到对方 sidecar 或 REST（不经过 Registry 转发，P0）
  → 对方本地 Guard / 包装器执行
  → 结果 + 双方 trace_id
```

P0 **不要**让 Registry 当反向代理。目录挂了不应阻断已建立的调用；调用挂了不应污染目录。

---

## 5. 工程模块拆解

仓库就是本仓。业务 Agent 只依赖 `sunny-client` 或一份 Card。

### 5.1 模块图

| 模块 | 职责 | P0 | 复杂度 | 依赖 |
|------|------|----|--------|------|
| **`sunny-card`** | Card / Skill / 映射文件的 JSON Schema、校验 CLI、A2A 0.3/1.0 字段兼容 | Must | S | 无 |
| **`sunny-registry`** | FastAPI：注册、更新、搜索、读 Card、心跳、审批。存储先 SQLite | Must | M | card |
| **`sunny-policy`** | 工作空间、角色、skill 授权、`data_class` / `side_effects` 门闩 | Must（先硬编码 + YAML） | M | registry |
| **`sunny-adapter`** | 独立进程：托管 Card、health、把 invoke 转到现有 HTTP | Must | M | card |
| **`sunny-client`** | Python：search / get_card / invoke | Must | S | registry API |
| **`sunny-admin`** | 最简 Web：列表、审批、禁用 | Should | S–M | registry |
| **`sunny-observe`** | 审计日志、与调用双方 `trace_id` 对账 | Should | S | registry |
| **`sunny-gateway`** | 统一代理、限流、mTLS | Could | L | 可换成 agentgateway |
| **`sunny-mcp`** | 把已批准技能暴露为 MCP | Could | M | registry |

### 5.2 首批接入怎么拆

不改业务进程。在业务仓外增加：

1. 从已有技能契约 **生成** 第一张 Card（人审后提交）。
2. 跑 `sunny-adapter`，映射 1 个技能做通。
3. 调用方用 `sunny_client` 或 REST 搜目录、按 skill id 调用。
4. 本仓用 `lab.echo` 证明第二进程，不把某个外部系统写成前提。

对方只需提供 **一个 URL + 槽字典**。sidecar 可以代写，他们的业务进程不动。

### 5.3 里程碑（粗估，1 人主路径）

| 阶段 | 周期 | 交付 | 验收 |
|------|------|------|------|
| **M0 纸面** | 本周 | 本文 + Card 草案 + 一张无密钥样例 | 字段能对上 A2A，且不含密钥 |
| **M1 Registry 最小** | 1–2 周 | 注册 / 搜索 / 心跳 / SQLite | pytest + curl 用例 |
| **M2 Adapter + 首租户** | 1–2 周 | sidecar 上架 1 个技能 | 另一进程能搜到并 invoke |
| **M3 第二租户** | 1 周 | 独立回声进程 | 调用方经 SUNNY 调到，Registry 不转发 |
| **M4 策略与管理台** | 1–2 周 | 审批、禁用、审计列表 | 未审批搜不到；无票调被拒 |
| **M5 可选 A2A 导出** | 以后 | `/.well-known/agent-card.json` + 兼容层 | 外部 A2A client 能读名片 |

合计到 M3：**大约 4–5 周**能证明「Hub 有用」。M4 才算能给同事用。

### 5.4 建议技术选型（可改，先锁方向）

- 语言：Python 3.10+（sidecar 与 Registry 同栈）
- API：FastAPI
- 存储：P0 SQLite；人多了再 Postgres
- Card：JSON Schema 为真源，生成 Type 或 Pydantic
- 鉴权：P0 服务 Token + 工作空间；P1 再接公司 SSO
- 部署：单进程 Registry + 每租户一个 adapter 容器

---

## 6. 可行性上的「条件」（什么时候开写代码）

2026-09-18 已拍板，全文见 [ADR-001](../decisions/ADR-001-开写前五件事.md)。摘要：

1. **首张名片**：只挂已契约化的技能；模型调用 / 建任务 / 整段聊天不开放。
2. **工作空间**：Agent 服务账号，不进个人 scratch。见 [ADR-002](../decisions/ADR-002-工作空间隔离.md)。
3. **被搜到**：已登记 Agent 默认可被其他已登记 Agent 发现。
4. **调用票**：接受 Registry 短时票。
5. **第二户**：用独立进程验收跨进程调用。本仓落地的是 `lab.echo`。

---

## 7. 建议的下一步

1. ~~冻结范围~~ 选型 B 已冻结。
2. ~~起草 Card Schema + 无密钥样例~~ 见 [`../../cards/lab.echo.sample.json`](../../cards/lab.echo.sample.json)。
3. M1 Registry 已另开并落地。跨进程示例是 `lab.echo`。

---

## 参考

- A2A Discovery：<https://a2a-protocol.org/v1.0.0/topics/agent-discovery/>
- A2A v1.0 定义（AgentCard / Skill）：<https://a2a-protocol.org/v1.0.0/definitions/>
- Google Cloud Agent Registry（A2A 与 NO_SPEC REST）：<https://docs.cloud.google.com/agent-registry/register-agents>
- Nacos AI Registry：<https://nacos.io/en/docs/latest/manual/user/ai/ai-registry-overview/>
- Microsoft Agent Registry：<https://learn.microsoft.com/en-us/entra/agent-id/identity-platform/what-is-agent-registry>
- AGNTCY Directory：<https://dir.agntcy.org/latest/> · <https://github.com/agntcy/dir>
- agentgateway：<https://agentgateway.dev/>
- 公网目录（对照，不采用）：<https://www.a2a-registry.org/> · <https://agorahub.dev/>
- Spring AI Alibaba A2A + Nacos：仓库 `alibaba/spring-ai-alibaba` 示例 README
- BeeAI ACP → A2A：LF AI & Data，2025-08
- 本系列：[`多Agent协作-行业口径与现网对照.md`](./多Agent协作-行业口径与现网对照.md)
- 现行：[`../decisions/ADR-001-开写前五件事.md`](../decisions/ADR-001-开写前五件事.md) · [`../specs/sunny-card.md`](../specs/sunny-card.md)
