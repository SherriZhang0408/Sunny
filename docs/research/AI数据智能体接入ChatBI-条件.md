# AI 数据智能体能否接入 ChatBI，以及何时接入

> **归档说明（2026-09-18）：** 红线仍有效。ChatBI 契约草稿已搁置，见 [`../specs/chatbi-skill-contract.md`](../specs/chatbi-skill-contract.md)。

| 项 | 内容 |
|----|------|
| 日期 | 2026-09-18 |
| 性质 | 架构判断（接入条件，不是开工清单） |
| 对照 | AI DATA AGENT / Hermes ↔ 同事维护的 ChatBI Agent（Gateway `:8095`） |
| 上游 | [`多Agent协作-行业口径与现网对照.md`](./多Agent协作-行业口径与现网对照.md) |

> 一句话：  
> **可以接，而且这正是「第二套独立 Agent 运行时」出现的时候。**  
> 但一期只许 **按契约调用 ChatBI 的能力**，不许把 Chat 对话整段转发给 `/v1/chat` 让它现场写 SQL。  
> 闭环融合主路径（D1/D2、`db.query_by_device`）仍然走自己的包装器。

---

## 0. 先对齐：我们今天已经「用过」ChatBI，但没有「调过」它

| 关系 | 现状 | 算不算接入 |
|------|------|------------|
| 知识 | 从 ChatBI `init_hive.sql` / `work/cn` 抽表结构、人机桥、临时需求进 `kb.retrieve` | 只读知识，**不是运行时接入** |
| 口径 | `pet_flag`、`dwm_robot_map_user`、家庭 4 类主表，对照 ChatBI 建表注释 | 规格对齐，**不发查询** |
| 取数 | `modules/fusion` 包装器，`ready=false`，无 Hive SELECT | 自己的虚集成，**不经 ChatBI** |
| 运行时 | ChatBI 已独立成 Agent：`POST /v1/chat`，L1–L5 Lane | **这是新变量** |

所以问题不是「能不能复用 ChatBI 的表知识」——已经在复用。  
问题是：**同事把问数 Agent 开放出来之后，Hermes 要不要、以及以什么身份去调它。**

---

## 1. 结论：能接，但要拆成三档，不要一档吃完

ChatBI Gateway 已经是跨进程的独立运行时（`:8095`，`/v1/chat`，自带 `trace_id` / `session_id` / Lane）。按上一份备忘的标准，对方 **有独立决策**（L3 clarify、L5 洞察），因此可以视为对等 Agent。  
现网仍然没有 A2A，**第一枪用 HTTP 契约即可**，不必先上 Registry。

```text
用户问 Hermes
  ├─ 闭环 / 图像 / 建任务 / 已有包装器
  │     → 本仓 Skill（禁止改口去 ChatBI）
  ├─ 数仓分析、模板圈选、指标解释、仓侧洞察
  │     → 满足第 3 节条件后，调 ChatBI 能力
  └─ 两者都要（例如「宠物家 × 同时刻图」）
        → Hermes 编排：ChatBI 出仓侧 subset，本仓包装器出图，应用层 JOIN
```

| 档 | 接法 | 现在能不能做 | 给谁用 |
|----|------|--------------|--------|
| **A. 知识继续同步** | 表结构 / 模板名 / 临时需求进 vault，走 `kb.retrieve` | **已经在做** | 「这张表什么意思」「临时需求有哪些」 |
| **B. 能力调用（推荐）** | Hermes 包装器调 ChatBI 的 **显式 action / 模板 ID / 固定槽**，把结果收成规范属性 | **条件满足后做** | 圈设备、配网/活跃/故障/宠物家等仓侧问题 |
| **C. 对等委托** | 把自然语言整段交给 ChatBI L3/L5，等它 clarify / 写 SQL / 讲故事 | **默认不做** | 只有人在环、且明确是「问数 / 洞察」时才开 |

B 是 Agent → 服务（更像 MCP 要解决的那类问题）。  
C 才是 Agent → Agent。同事「开放了一个 Agent」不等于我们必须走 C。

---

## 2. 为什么不能整段转发

本仓取数合同已经写死：

- 智能体 **不许拼 SQL**，Chat 里 **不许出 SQL / endpoint**
- 新查询形状是 **发版**（改 YAML / 模板），运行时拒绝
- 一期是 **浅接入**，不深对接统一数据平台（Charter §5.2 红线 5）
- 融合要的是 `did + iotType + 时间窗` 上的 **规范属性**，不是一篇 NL2SQL 作文
- 目前融合侧 **没有 Hive 业务行权限**；若经 ChatBI 执行 SQL，等于换一条路径提权，必须单独授权

ChatBI 的强项正好在另一侧：

| Lane | 做什么 | 对 Hermes 的风险 |
|------|--------|------------------|
| L1 模板 | 已知主题渲染 SQL（如样本圈选） | 低：槽位固定，最像本仓包装器 |
| L2 Guard | 人写 SQL 的只读检查 | 中：给开发者，不给闭环主路径 |
| L3 NL2SQL | 现场规划 SQL，可多轮 clarify | 高：和「禁止现场写 SQL」冲突 |
| L4 知识 | 仓名词解释 | 低：与 `kb.retrieve` 重叠，可互为备份 |
| L5 洞察 | 分析报告 | 高：叙事不稳定，不能当 D1/D2 验收源 |

因此：**接 L1（以及将来契约化的只读结果接口）优先；L3/L5 默认不进闭环 DAG。**

---

## 3. 满足什么条件才接入（检查清单）

下面全部是 **接入门闩**。缺任何一条，就继续只用档 A，不要对 `:8095` 发业务请求。

### 3.1 对方先开放「能力」而不只是「聊天框」

同事说「开放了一个 Agent」，Hermes 需要的是可登记的能力，不是 Web UI。

必须拿到并写进本仓目录（资产卡或算子 JSON）的内容：

1. **基址**：内网 URL，谁运维，环境（dev / 生产）分开。
2. **契约**：`POST /v1/chat` 的请求 / 响应字段；至少要有 `trace_id`、`lane`、`status`、结构化 `artifacts`。
3. **显式 action / 模板 ID**：例如 `template.render` + 模板名，或只读结果接口。禁止只给「把 query 丢进去」。
4. **槽位字典**：必须能传入 `did` / `sn` / `iot_robot_type` / 时间窗（或 ChatBI 等价字段），并与 Association Contract 对齐。
5. **能力边界**：哪些表、哪些 Lane、是否执行 SQL（`CHATBI_EXECUTE_ENABLED`）、返回的是 SQL 文本还是行数据。
6. **失败语义**：`clarify`、Guard 拒绝、超时、无权限分别是什么 `status`，Hermes 怎么降级。

没有 3 和 4，就还不能当包装器后端，只能当人工问数入口。

### 3.2 发现与访问分离（权限）

沿用壳层 L1–L4，不要用 WebUI 角色去冒充仓权限。

| 层 | 接入 ChatBI 时要有什么 |
|----|------------------------|
| 身份 | 服务账号或网关 Token，**不要**复用同事个人登录；飞书白名单与 ChatBI 会话分开 |
| 目录 | 本仓登记「ChatBI 哪些模板 / action 可用」，人审后才能进 Skill |
| 调用 | 每次请求带身份 + 槽校验；ChatBI 侧仍走自己的 Guard（只读、表白名单、分区） |
| 执行 | **默认只拿计划 / 模板结果，不执行。** 只有数据侧书面授权、且本仓 `ready` 策略允许时，才打开「返回行」 |
| 出口 | Chat 回复仍禁止 SQL 原文；SQL 只进审计 / scratch，给人看的是规范属性或「已交给 ChatBI，trace=…」 |

现网融合侧没有 SELECT 时：**即使 ChatBI 能执行，Hermes 也不许借它绕过「无业务行权限」。**  
两条路径的权限要同时成立，不能「我这边没账号、那边有账号就偷偷查」。

### 3.3 业务上真的需要 ChatBI，而不是包装器缺人补

只在出现下面这些意图时才路由过去：

| 可以交给 ChatBI | 必须留在本仓 |
|------------------|--------------|
| 仓侧即席分析、已有 L1 模板圈选 | `db.query_by_device` / lifecycle / scenes |
| 「临时需求有哪些」、表口径解释（L4 或知识同步） | 图像 ES、CVAT 建任务、标注仓 `ai_task_info` |
| 人在环的洞察报告（L5，单独入口） | D1/D2 黄金关联、DatasetHandle 漏斗 |
| 以后：仓侧 subset 作为融合的一侧输入 | 现场发明 JOIN / 物化人机宽表 |

路由规则建议写死在 Skill，不要靠模型自己决定「这次去不去 ChatBI」。  
问「用户大数据临时需求都有哪些」今天已经规定走 `kb.retrieve`，**不要改口成调 ChatBI Agent。**

### 3.4 编排与验收还得是 Hermes 的

- 跨源 JOIN（仓 × 图）仍在 **应用层**，默认 60s 窗口，不物化宽表。
- W1/W2/S1、D1/D2 的成功率与 Trace **不以 ChatBI 作文为准**。
- ChatBI 的 `trace_id` 要写进本仓 RunRecord / 包装器审计，两边能对上。
- L3 若返回 `clarify`：只许 **回问当前用户**，不许 Hermes 替用户猜槽后自动执行。
- 超时、Guard 失败、Lane 漂移：本仓降级为「无法实现 / 请用人审」，禁止换 L3 再赌一次。

### 3.5 Charter 与发版

- 仍是 **浅接入**：HTTP 调对方 Gateway，不把 ChatBI 源码、Coral 工作流、Hive 账号搬进 Hermes。
- 新模板 / 新槽 = **两边发版**。ChatBI 加模板，本仓加资产卡和路由，才能上线。
- 改 JOIN 键或任务主键必须升 `AssociationContract.v2`，与接不接 ChatBI 无关。

---

## 4. 推荐落地顺序（条件过了之后）

| 步 | 做什么 | 验收 |
|----|--------|------|
| 1 | 同事给出 1 个 L1 模板的稳定契约（槽 + 是否执行 + 示例 `trace_id`） | curl 能复现，与文档一致 |
| 2 | 本仓加资产卡 `CHATBI.API.Query.v1`（planned → available）和只读包装器 | Chat 填槽、拒未知槽、回复无 SQL |
| 3 | 选 1 个已核表主题（建议：宠物家 `pet_flag` 或配网），只返回规范属性 | 与 fixture / 仓侧对账一致 |
| 4 | 需要「仓侧圈设备 → 再取图」时，Hermes DAG 两节点：ChatBI subset + 本仓 ImageSample | 应用层窗口 JOIN，不落宽表 |
| 5 | 若双方都要互发现、委托长任务 | 再评估 A2A Card / 中心注册；现在不必 |

没走完第 1 步，就还只是「同事开了一个聊天框」，不是「智能体接入了 ChatBI」。

---

## 5. 一页对照：同事开放 Agent 之后，我们怎么对外说

| 问法 | 答法 |
|------|------|
| 能不能接？ | 能。ChatBI 已是独立问数 Agent；我们按能力调用，不按聊天转发。 |
| 现在接了吗？ | 知识层已接。运行时未接。融合仍 mock，也还没有双方签字的 action 契约。 |
| 什么条件接？ | 有基址与鉴权、有显式模板/action、槽位对齐身份和时间窗、执行权限单独开、Chat 不泄 SQL、失败可降级、路由写死。 |
| 接了会不会替代包装器？ | 不会。包装器管闭环关联；ChatBI 管仓侧问数与已有模板。 |
| 要不要上 A2A？ | 先 HTTP。真要双向委托和任务生命周期再谈。 |

---

## 参考

- `AIDataAgent/docs/product/智能体取数包装器-口径.md`
- `AIDataAgent/docs/product/登录鉴权与权限分层.md`
- `AIDataAgent/docs/product/多源数据融合-一期落地建议.md`
- `AIDataAgent/立项/AI数据智能体-技术Charter立项报告.md` §5.2 红线 5
- ChatBI Gateway：`POST /v1/chat`（L1 模板 · L2 Guard · L3 NL2SQL · L4 知识 · L5 洞察）
- 现行契约草稿：[`../specs/chatbi-skill-contract.md`](../specs/chatbi-skill-contract.md)
