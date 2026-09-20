# SUNNY MCP 发现面

| 项 | 内容 |
|----|------|
| 状态 | 已落地 |
| 代码 | [`../../sunny_registry/mcp.py`](../../sunny_registry/mcp.py)、[`../../sunny_registry/mcp_stdio.py`](../../sunny_registry/mcp_stdio.py) |
| 传输 | Registry 进程内 JSON-RPC 2.0（Python 3.8，不上官方 `mcp` SDK）；stdio 代理转发到同一 `/mcp` |

Registry **只发现、不代调**。不签发票、不暴露 `invoke`、不把 MCP Server / Skill 收进同一张 agents 表。访问方式是「sidecar URL + 出票 REST」，不是把业务调用收进 MCP。

`initialize` 与 `GET /mcp` 带 `instructions`：何时来 Registry、何时不要来。对方智能体把本 MCP 挂上后，才能在超界时自己决定来搜。

## 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/mcp` | 工具清单、`instructions`、stdio 启动命令（匿名可读） |
| POST | `/mcp` | JSON-RPC：`initialize`、`tools/list`、`tools/call`、`ping` |

鉴权复用 `get_principal`。匿名只能调 `join`；其余工具需要 `sak_` 或 Hub 会话。

stdio（其他智能体本地挂接）：

```bash
SUNNY_REGISTRY_URL=http://<registry-host>:8088 \
SUNNY_AGENT_KEY=sak_… \
python3 -m sunny_registry.mcp_stdio
```

`SUNNY_AGENT_KEY_FILE` 可指向服务文件；路径含 `scratch` 会拒。

## 工具

| 工具 | 对应 REST | 返回 | 不返回 |
|------|-----------|------|--------|
| `list_agents` | `GET /agents`（仅 online、对等可见） | 公开技能、sidecar、出票路径 | 票、key、restricted 技能 |
| `search_registry` | `GET /search`（`q` 走 FTS5） | 技能摘要 | 接口 URL、票、key |
| `get_card` | 阶段 1 公开卡 | 公开卡 + `access` 配方 | restricted 技能、已签发的票 |
| `get_extended_card` | `GET /agents/{id}/extended` | 完整卡 | 票、key |
| `describe_access` | 无单独 REST | sidecar / invoke path / `POST /tickets` 配方 | 已签发的票 |
| `list_card_changes` | `GET /card-changes` | 升版游标 | 票 |
| `join` | `GET /api/v1/join` 摘要 | `when_to_use` / `when_not_to_use` | enroll token |

没有 `tickets` / `invoke`。出票与调用仍走 REST + sidecar。看见名片 ≠ 能调用。

## Cursor / 其他 MCP 客户端

本机 Registry 默认 `http://127.0.0.1:8088`。

HTTP：

```json
{
  "mcpServers": {
    "sunny-registry": {
      "url": "http://127.0.0.1:8088/mcp",
      "headers": {
        "X-Sunny-Agent-Key": "sak_…"
      }
    }
  }
}
```

stdio（需能 import 本仓，或把仓库根设为 `cwd`）：

```json
{
  "mcpServers": {
    "sunny-registry": {
      "command": "python3",
      "args": ["-m", "sunny_registry.mcp_stdio"],
      "env": {
        "SUNNY_REGISTRY_URL": "http://127.0.0.1:8088",
        "SUNNY_AGENT_KEY": "sak_…"
      }
    }
  }
}
```

Hub 会话则带登录 token。Hermes 可选 Skill `sunny.discover` 可继续用 REST；不强制改道 MCP。
