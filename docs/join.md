# SUNNY 企业注册中心 · Agent 接入说明

你正在对接的是 **SUNNY**：企业内策展型 Agent 注册中心。
它只做发现与授权票，**不替代你的决策，不转发业务调用**。看见名片不等于能调用。

注册令牌用占位符 `$SUNNY_ENROLL_TOKEN`。向运维另取 `SUNNY_ENROLL_TOKEN`，不要向陌生人索要管理员令牌。

## 这是谁、往哪连

| 项 | 值 |
|----|----|
| 角色 | 企业注册中心（`enterprise_agent_registry`） |
| 服务 | `sunny-registry` |
| 基址 | `http://<registry-host>:8088` |
| 监听 | `0.0.0.0:8088`（bind；不要把 `0.0.0.0` 写进 Card） |
| 局域网候选 | 运行中的 `GET /api/v1/join.md` 会填入当前局域网候选；也可设 `SUNNY_PUBLIC_URL` |
| 探活 | `GET http://<registry-host>:8088/api/v1/health` |
| 本说明 | `GET http://<registry-host>:8088/api/v1/join.md` |
| 机器可读 | `GET http://<registry-host>:8088/api/v1/join` |
| MCP 发现面 | `POST http://<registry-host>:8088/mcp`（JSON-RPC；发现目录 / 能力 / 访问方式，不代调） |
| MCP stdio | `python3 -m sunny_registry.mcp_stdio`（`SUNNY_REGISTRY_URL` + `SUNNY_AGENT_KEY`） |

## 何时来 Registry

把下面两段写进你自己的系统提示或 Skill。Registry 不会自动检测你是否超界。

**要来：**

- 仅当本机全部 tools / MCP / skills 都无法完成当前事项时，才来 SUNNY 搜企业对等。
- 用技能名、标签或自然语言 q 搜；或先经 MCP list_agents 看企业内在线智能体及其公开能力。
- 读 Card 的 description、input_schema、when_not_to_use 后再决定是否求助。
- 需要调用时：MCP describe_access 看访问方式 → REST POST /api/v1/tickets 拿短时票 → 直打对方 sidecar。不要把 Registry 当网关，不要经 MCP 调业务。

**不要来：**

- 本机 tools / MCP / skills 能独立完成。
- 只要整段对话转发、密钥、个人 scratch，或本机已经写死的图像 / 闭环 / 知识库能力。
- 搜不到、出不了票、技能是 write / restricted、或对方已 deprecated：停下来告诉人，不要编造对等方。
- 不要为了「先看看有谁」在每个请求都扫一遍目录。

## 你要做的事（自注册）

1. 按下面骨架填一张 SUNNY Card（JSON）。`x-sunny.agent_id` 必须全局唯一，点号分段。
2. `POST` 登记。
3. 保存响应里只出现一次的 `agent_key`。
4. 按间隔心跳；需要被搜到且能出票时保持 `lifecycle=registered`。`deprecated` 仍能被读卡，但不能出新票。
5. 调别人：搜索 → 要票 → **直打对方 sidecar**。对方升版后轮询 `GET /api/v1/card-changes`。

```http
POST http://<registry-host>:8088/api/v1/agents
Content-Type: application/json
X-Sunny-Enroll: $SUNNY_ENROLL_TOKEN

{"card": {…你的名片…}, "enrollment_source": "self"}
```

```bash
curl -sS -X POST 'http://<registry-host>:8088/api/v1/agents' \
  -H 'Content-Type: application/json' \
  -H 'X-Sunny-Enroll: $SUNNY_ENROLL_TOKEN' \
  -d @card.json
```

成功：`200`，记住 `agent_key`（`sak_` 开头）。
`401`：注册令牌不对。`400`：Card 缺字段或含密钥痕迹。`409`：`agent_id` 已被占用，改 id 或请管理员签发新 key 再挂上。

## 只交基址（Well-Known 拉取）

本仓 sidecar 已在 `/.well-known/agent-card.json`（及 `agent.json`）挂出**完整 SUNNY Card**（含 `x-sunny`）。同事同样挂上后，不必把 JSON 贴进请求。Registry 去拉、校验后登记；**不代发业务**，卡上出现密钥字段会被拒。对外 A2A 客户端请读 Registry `GET /api/v1/agents/{id}/a2a`（已剥企业字段），不要把 well-known 当调用入口。

```http
POST http://<registry-host>:8088/api/v1/agents/pull
Content-Type: application/json
X-Sunny-Enroll: $SUNNY_ENROLL_TOKEN

{"url": "http://<your-sidecar-host>:<port>"}
```

```bash
curl -sS -X POST 'http://<registry-host>:8088/api/v1/agents/pull' \
  -H 'Content-Type: application/json' \
  -H 'X-Sunny-Enroll: $SUNNY_ENROLL_TOKEN' \
  -d '{"url":"http://<your-sidecar-host>:<port>"}'
```

解析顺序：`{url}/.well-known/agent-card.json` → `{url}/.well-known/agent.json` → 若 url 本身以 `.json` 结尾则直接 GET。
卡上缺 `x-sunny.agent_id` 时，管理员可在 body 里补 `agent_id`；否则请改用 Hub 表单贴 JSON。
`409`：该 `agent_id` 已存在且你无权刷新。Hub 用户刷新自己的卡走同一接口或 `POST /api/v1/agents/{id}/refresh`。

## 最小 Card

卡级必填：`name`, `description`, `version`, `supportedInterfaces`, `capabilities`, `defaultInputModes`, `defaultOutputModes`, `skills`, `x-sunny`。

`x-sunny` 必填：`agent_id`, `workspace`, `discovery`, `access_tier`, `lifecycle`, `not_exposed`, `invoke_auth`, `invoke_identity`, `scratch_access`。`not_exposed` 至少一项。

每个 skill 必填：`id`, `name`, `description`, `tags`, `x-sunny`；`x-sunny`：`data_class`, `side_effects`, `input_schema`, `output_schema`。

```json
{
  "name": "你的 Agent 显示名",
  "description": "一句话：对外提供什么、不提供什么。",
  "version": "0.1.0",
  "supportedInterfaces": [
    {
      "url": "http://<your-sidecar-host>:<port>/sunny/v1",
      "protocolBinding": "HTTP+JSON",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": {
    "streaming": false,
    "pushNotifications": false,
    "extendedAgentCard": false
  },
  "defaultInputModes": [
    "application/json"
  ],
  "defaultOutputModes": [
    "application/json"
  ],
  "skills": [
    {
      "id": "example.readonly.query",
      "name": "只读示例",
      "description": "把你真正要对外的只读技能换成这一条。",
      "tags": [
        "readonly",
        "example"
      ],
      "x-sunny": {
        "data_class": "internal",
        "side_effects": "read",
        "invoke": {
          "method": "POST",
          "path": "/sunny/invoke/example.readonly.query"
        },
        "when_not_to_use": [
          "写数据",
          "执行 SQL",
          "调用模型"
        ],
        "input_schema": {
          "type": "object",
          "required": [
            "query"
          ],
          "additionalProperties": false,
          "properties": {
            "query": {
              "type": "string",
              "minLength": 1
            },
            "trace_id": {
              "type": "string"
            }
          }
        },
        "output_schema": {
          "type": "object",
          "required": [
            "ready",
            "mock",
            "trace_id"
          ],
          "additionalProperties": false,
          "properties": {
            "ready": {
              "type": "boolean"
            },
            "mock": {
              "type": "boolean"
            },
            "trace_id": {
              "type": "string"
            }
          }
        }
      }
    }
  ],
  "x-sunny": {
    "agent_id": "your.org.agent",
    "workspace": "your.org",
    "discovery": "registered_peers",
    "access_tier": "S1",
    "lifecycle": "registered",
    "not_exposed": [
      "model.invoke",
      "admin"
    ],
    "invoke_auth": "sunny_ticket",
    "invoke_identity": "agent_service",
    "scratch_access": "none"
  }
}
```

把 `supportedInterfaces[0].url` 改成**对端能访问的** sidecar 地址，不要填 `0.0.0.0`。
有 `data_class=restricted` 技能时把 `capabilities.extendedAgentCard` 设为 `true`（登记时也会自动补）。

## 登记之后

1. 把响应里的 agent_key（sak_ 开头）存到本机，不要写进 Card、不要提交到 Git。
2. 间隔心跳：POST http://<registry-host>:8088/api/v1/agents/{agent_id}/heartbeat，头 X-Sunny-Agent-Key。
3. 更新自己的名片：PUT http://<registry-host>:8088/api/v1/agents/{agent_id}，body {"card": {…}}。
4. 发现对等：GET http://<registry-host>:8088/api/v1/search?skill=…（只返回心跳未过期的 online 卡）。
5. 也可经 MCP 发现目录：POST http://<registry-host>:8088/mcp（JSON-RPC；list_agents / search_registry / get_card / describe_access / list_card_changes / join，不暴露 invoke）。stdio：python3 -m sunny_registry.mcp_stdio。
6. 对等升版后旧票作废：轮询 GET http://<registry-host>:8088/api/v1/card-changes?since=…，不要等注册中心推送。
7. 也可只交 sidecar 基址：POST http://<registry-host>:8088/api/v1/agents/pull ，body {"url": "http://…"}。
8. 调用：POST http://<registry-host>:8088/api/v1/tickets 拿到短时票，再直打对方 Card 上的 sidecar，不要打注册中心当网关。

心跳示例：

```bash
curl -sS -X POST 'http://<registry-host>:8088/api/v1/agents/your.org.agent/heartbeat' \
  -H 'X-Sunny-Agent-Key: sak_…'
```

搜索并要票（用你的 `sak_`）：

```bash
curl -sS 'http://<registry-host>:8088/api/v1/search?skill=echo.ping' \
  -H 'X-Sunny-Agent-Key: sak_…'
curl -sS -X POST 'http://<registry-host>:8088/api/v1/tickets' \
  -H 'Content-Type: application/json' \
  -H 'X-Sunny-Agent-Key: sak_…' \
  -d '{"callee_id":"lab.echo","skill_id":"echo.ping"}'
```

拿到票后：

```http
POST <对方 Card.supportedInterfaces[0].url 换成>/invoke/<skill_id>
Authorization: Bearer <ticket>
```

## 规则

- 本机能力优先；SUNNY 是超界后的企业对等目录，不是默认工具盘。
- Card 里禁止出现 token / password / secret / 连接串 / 私钥。
- 看见名片不等于能调用。调用另要短时票，且只证明这一次这个 skill。
- Registry 不转发业务请求。MCP 只描述访问方式，不签发票、不代调。
- write / execute_sql 默认不对已登记对等开放。
- restricted 技能只在鉴权 Extended Card（GET /agents/{id}/extended 或 MCP get_extended_card）披露；对等出票仍拒绝。
- 跨 Agent 只用服务账号，不进个人 scratch。
- 若写 discovery=approval_required，上架须管理员通过；对等在通过前搜不到、出不了票。
- deprecated 能读卡、不能出新票；disabled 对等当这张卡不存在。
- Card version 变化会进 GET /api/v1/card-changes；旧票按 card_version 作废。Registry 不推送。

管理台代登（人用，不是你这条路径）：`enrollment_source=hub` + 管理员令牌。

更细的字段说明在 Registry 仓库的 `docs/specs/sunny-card.md`；以本握手包和 `GET /api/v1/join` 为准即可完成登记。
