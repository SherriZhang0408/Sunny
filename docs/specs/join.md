# SUNNY Join Packet（接入说明）

| 项 | 内容 |
|----|------|
| 读者 | 尚未登记的外部 Agent，以及把它拷走的人 |
| 真源 | 运行中的 `GET /api/v1/join.md`；仓库快照 [`../join.md`](../join.md) |
| 状态 | 已落地 |

## 需求

1. 工程能给出**一份自包含 Markdown**：说明「这是企业注册中心」，对方 Agent 读完就能自注册。
2. 运行中的 Registry 能**按当前基址导出**同一份说明，而不是写死 `127.0.0.1`。
3. 进程**监听** `0.0.0.0`，局域网可连；**宣告**地址必须是对端能打到的 URL，**禁止**把 `0.0.0.0` 写进 Card 或握手包。
4. 默认可匿名拉取握手包（未登记也能读，否则鸡生蛋）。**注册令牌默认不写进文件**。管理员可选择带令牌导出。
5. 看见名片 ≠ 能调用。握手包必须写清：登记后拿 `sak_`，调用走短时票，直打对方 sidecar。

## 监听与宣告

| 概念 | 环境变量 | 默认 | 用途 |
|------|----------|------|------|
| 监听地址 | `SUNNY_HOST` | `0.0.0.0` | bind，接受局域网连接 |
| 监听端口 | `SUNNY_PORT` | `8088` | bind |
| 对外基址 | `SUNNY_PUBLIC_URL` | 探测到的局域网 IPv4 + 端口 | 写进握手包、health |
| Adapter 监听 | `SUNNY_ADAPTER_HOST` | `0.0.0.0` | sidecar bind |
| Adapter 对外 | `SUNNY_ADAPTER_PUBLIC_URL` | 局域网 IP + `8091` + `/sunny/v1` | 写入自己的 Card |

`SUNNY_PUBLIC_URL` 未设时：优先用本机非回环 IPv4；没有则回落 `http://127.0.0.1:8088`。请求从 `Host` 进来时，若 Host 不是 `0.0.0.0`，JSON 里额外给出 `request_url`，但不覆盖已解析的 `public_url`（避免本机打开 Hub 时把 `127.0.0.1` 导出给局域网对端）。

启动：

```bash
python3 -m sunny_registry
python3 -m sunny_adapter
```

仍可用 uvicorn，但必须 `--host 0.0.0.0`。

## API

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/v1/health` | 无 | 探活；含 `public_url`、`join` |
| GET | `/api/v1/join` | 无 | 机器可读握手包（JSON） |
| GET | `/api/v1/join.md` | 无 | 给人/Agent 读的 Markdown |
| GET | `/api/v1/join.md?include_token=1` | 管理员 | 把真实 `SUNNY_ENROLL_TOKEN` 写进文档 |
| GET | `/api/v1/join.md?download=1` | 同左 | `Content-Disposition: attachment` |

`include_token=1` 且非管理员 → `403`。匿名响应里令牌位置固定为 `$SUNNY_ENROLL_TOKEN`。

自注册（已有，握手包只引用）：

```http
POST /api/v1/agents
X-Sunny-Enroll: $SUNNY_ENROLL_TOKEN
Content-Type: application/json

{"card": {…}, "enrollment_source": "self"}
```

成功：`200`，`agent_key`（`sak_`）只出现这一次。`409`：`agent_id` 已占用。

## JSON 字段（`GET /api/v1/join`）

| 字段 | 含义 |
|------|------|
| `service` | `sunny-registry` |
| `role` | `enterprise_agent_registry` |
| `public_url` | 对端应使用的基址 |
| `listen` | `{host, port}` 实际 bind |
| `lan_urls` | 探测到的局域网候选 |
| `join_md` | `/api/v1/join.md` |
| `enroll` | 方法、路径、头、`enrollment_source`、令牌占位或真实值、`token_included` |
| `card_required` | 卡级 / 技能级必填 |
| `card_skeleton` | 可改的最小名片 |
| `after_enroll` | 存 key、心跳、搜索、要票、直打 sidecar |
| `rules` | 禁写密钥、发现≠访问、Registry 不转发 |

## 非目标

- 一次性邀请码（以后再做）
- 把 Registry 改成调用网关
- 在握手包里放 admin token 或 ticket secret
