# SUNNY Adapter + Client（M2）

| 项 | 内容 |
|----|------|
| 示例 | `lab.echo`：回声 HTTP + 映射 sidecar。未设置名片时，进程仍读取仓内历史样例，只给既有测试用 |
| 调用 | Client 向 Registry 搜卡、拿短时票，**直打 sidecar**。Registry 不转发 |

## 进程

```text
sunny-client（另一进程）
  → Registry search(skill)
  → Registry tickets
  → POST http://127.0.0.1:8091/sunny/invoke/<skill>
       Authorization: Bearer <ticket>
  → sidecar 向 Registry verify 票
  → 本地执行；调用未结束时按间隔再验一次
  → 再验失败：丢掉结果，HTTP 上游关掉本次连接，对调用方 `409 ticket revoked`
  → Client 可选 POST /invocations 记一笔边
```

## 环境变量

| 变量 | 默认 | 用途 |
|------|------|------|
| `SUNNY_REGISTRY_URL` | `http://127.0.0.1:8088` | 本机连 Registry；跨机改成握手包里的基址 |
| `SUNNY_ADAPTER_HOST` | `0.0.0.0` | sidecar 监听 |
| `SUNNY_ADAPTER_PUBLIC_URL` | 局域网 IP + `:8091/sunny/v1` | 写入 Card 的对外接口，不会是 `0.0.0.0`。第二户 echo sidecar 用 `:8093` |
| `SUNNY_ADAPTER_CARD` | 不设则用仓内历史样例；示例请设 `cards/lab.echo.sample.json` | 挂上时用的名片 |
| `SUNNY_ADAPTER_KEY_FILE` | `data/adapter-keys/<agent_id>.key` | sidecar 自己的 `sak_` |
| `SUNNY_ADMIN_TOKEN` / `SUNNY_ENROLL_TOKEN` | `sunny-dev-*` | 409 后签发 key / 首次自注册 |
| `SUNNY_ADAPTER_MAPPING` | `sunny_adapter/mappings/<agent_id>.json` | 技能路由：`local` 或 HTTP。缺省文件存在则自动加载 |
| `SUNNY_ADAPTER_REVOKE_POLL_S` | `0.25` | 调用未结束时复查验票的间隔；小于 0.05 按 0.05 |

Hub 已登记同一 `agent_id` 时，sidecar **只挂接口、不改 enrollment_source**（仍是 `hub`）。

## 启动

先 Registry，再 sidecar：

```bash
python3 -m sunny_registry
python3 -m sunny_echo
ECHO_URL=http://127.0.0.1:8092 SUNNY_ADAPTER_CARD=cards/lab.echo.sample.json \
SUNNY_ADAPTER_MAPPING=sunny_adapter/mappings/lab.echo.json SUNNY_ADAPTER_AGENT_ID=lab.echo \
SUNNY_ADAPTER_PORT=8093 python3 -m sunny_adapter
```

Sidecar 启动时会：

1. 用 enroll token 自注册；若 Hub 已登记过同一 `agent_id`，管理员签发一把新 key 再挂上
2. 把 Card 里的 `supportedInterfaces[0].url` 改成 `SUNNY_ADAPTER_PUBLIC_URL`
3. 按 `SUNNY_ADAPTER_HEARTBEAT_S` 心跳
4. 匿名挂出完整 SUNNY Card：`/.well-known/agent-card.json`、`/.well-known/agent.json`、`/sunny/v1/card`（三份相同，带 `ETag`）

钥匙写在 `data/adapter-keys/<agent_id>.key`，不进 Card、不进 Git。剥掉 `x-sunny` 的 A2A 导出在 Registry `GET /api/v1/agents/{id}/a2a`，不在 sidecar。

## 映射与槽校验（P1）

验票之后、执行之前，按 Card 里该技能的 `x-sunny.input_schema` 校验 `slots`。多出来的键（例如 `sql`）或缺少 `anyOf` 必填 → `400`。

新租户只交 Card + 映射，不必再写 Python handler：

```json
{
  "agent_id": "lab.echo",
  "routes": [
    {
      "skill_id": "echo.ping",
      "handler": "http",
      "method": "POST",
      "url": "${ECHO_URL}/v1/echo",
      "map": { "q": "$.slots.query" }
    }
  ],
  "heartbeat": { "url": "${ECHO_URL}/health" }
}
```

`url` / `headers` 支持 `${VAR}` 与 `${VAR:-default}`。URL 必须是 http(s)，且来自映射文件，不接受 slots 里的地址。下游失败回 `ready=false`，不把密钥写进错误。`/health` 带 `mapping.routes`；若配置了 `heartbeat.url` 再探下游，**不挡** Registry 心跳。

也接受 `.yaml`（需本机已装 PyYAML）。无映射文件时走内置本地 handler（仅历史样例）。

## 另一进程调用

```bash
python3 -m sunny_client --skill echo.ping --slots '{"query":"hello"}'
```

环境变量：`SUNNY_REGISTRY_URL`、`SUNNY_AGENT_KEY`（调用方）、`SUNNY_ADMIN_TOKEN`（本地可代签票）、`SUNNY_CALLER_ID`（管理员代签时的 caller，默认 `lab.inspector`）。

调用方走这条 CLI 或 REST。不要把 Registry 当对话入口。
