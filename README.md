# SUNNY · Agent Hub

企业内策展型 Agent 注册中心。名字来自电影 *I, Robot* 里的机器人桑尼：不替代各智能体的决策，只让它们按名片互相发现、按策略互相调用。

M1：Registry API + Docker Hub 风格管理台。不转发业务调用。  
M2：`aidata.hermes` sidecar + `sunny_client`，另一进程可搜卡、拿票、直打 sidecar。  
第二户：`lab.echo` 真 HTTP 回声（`:8092`）+ 映射 sidecar（`:8093`）。

## 启动

```bash
python3 -m pip install -r requirements.txt
python3 -m sunny_registry
python3 -m sunny_adapter
# 第二户（可选）：回声 :8092 + echo sidecar :8093
# ECHO_URL=http://127.0.0.1:8092 SUNNY_ADAPTER_CARD=cards/lab.echo.sample.json \
# SUNNY_ADAPTER_MAPPING=sunny_adapter/mappings/lab.echo.json SUNNY_ADAPTER_AGENT_ID=lab.echo \
# SUNNY_ADAPTER_PORT=8093 python3 -m sunny_adapter
```

默认监听 `0.0.0.0`（局域网可连）。浏览器打开本机 <http://127.0.0.1:8088> ，或用握手包里的局域网基址。本地默认管理员 `admin` / `sunny-dev-admin`，开发者 `developer` / `sunny-dev-developer`。

把说明交给其他 Agent：`GET /api/v1/join.md`，或管理台「发布登记 → 发给智能体」。仓库快照见 [docs/join.md](docs/join.md)。

另一进程调用：

```bash
python3 -m sunny_client --skill collect.strategy.query --slots '{"mission_name":"living_room"}'
python3 -m sunny_client --skill echo.ping --slots '{"query":"hello"}'
```

```bash
python3 -m pytest -q
python3 scripts/validate_card.py cards/aidata.hermes.sample.json
```

## 一期范围

| 项 | 现状 |
|----|------|
| 首批租户 | `aidata.hermes`（Hub 填入 + sidecar 挂上）+ 演示对等 `lab.inspector` + 第二户 `lab.echo`（真 HTTP 回声） |
| 对外技能 | `collect.strategy.query`（进程内枚举）、`collect.volume.query`（无 AIDATA 包装器则 `ready=false`）。`lab.echo`：`echo.ping` 可搜可调；`echo.secret` 仅 Extended Card。映射文件可把技能接到本地 handler 或下游 HTTP；invoke 按 Card `input_schema` 校验槽 |
| 发现 | 已登记且 `discovery=registered_peers` 可互发现；`approval_required` 须管理员通过；搜索默认只要 `online`（心跳未过期，或最近探活成功）；`restricted` / 写技能不出目录与公开卡；升版后旧票作废。Registry 周期探活 / 重抓。sidecar 挂 `/.well-known/agent-card.json`；`GET /agents/{id}` 对等拿公开卡，`/extended` 拿完整卡，`/a2a` 再剥企业字段。MCP：`POST /mcp` 或 `python3 -m sunny_registry.mcp_stdio` 发现目录 / 能力 / 访问方式，不代调 |
| 调用身份 | Agent 服务账号；不进个人 scratch |
| 管理台 | 管理员/开发者登录；Explore / Card / 编辑 / 变更历史 / 调用关系 / 活动（搜索·出票·调用可按 trace_id 对账） / Publish / 账号管理 / 系统设置 |
| 权限 | 管理员全权限；开发者看名片、发布自己的智能体，且只能改/删自己创建的卡 |
| 第二户 | `lab.echo` 已落地（回声 HTTP + 映射 sidecar）。ChatBI 意向保留；八字段表搁置 |

## 文档

- [工程说明 / API / 对外汇报（HTML）](docs/site/index.html)
- [文档地图](docs/README.md)
- [同类项目对照](docs/research/同类项目对照.md)
- [给其他 Agent 的接入说明](docs/join.md)
- [Join Packet 规格](docs/specs/join.md)
- [Registry API](docs/specs/registry-api.md)
- [Adapter + Client](docs/specs/adapter.md)
- [MCP 发现面](docs/specs/mcp-discovery.md)
- [第二户 lab.echo](docs/specs/lab-echo.md)
- [开写前五件事](docs/decisions/ADR-001-开写前五件事.md)
- [Card 规格](docs/specs/sunny-card.md)
