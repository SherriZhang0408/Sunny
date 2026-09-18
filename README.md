# SUNNY

企业内 Agent Hub。名字来自电影 *I, Robot* 里的机器人桑尼：不替代各智能体的决策，只让它们按名片互相发现、按策略互相调用。

M1：Registry API + Docker Hub 风格管理台。不转发业务调用。  
M2：`aidata.hermes` sidecar + `sunny_client`，另一进程可搜卡、拿票、直打 sidecar。

## 启动

```bash
python3 -m pip install -r requirements.txt
python3 -m sunny_registry
python3 -m sunny_adapter
```

默认监听 `0.0.0.0`（局域网可连）。浏览器打开本机 <http://127.0.0.1:8088> ，或用握手包里的局域网基址。本地默认管理员 `admin` / `sunny-dev-admin`，开发者 `developer` / `sunny-dev-developer`。

把接入说明交给其他 Agent：`GET /api/v1/join.md`，或管理台「发布登记 → 导出接入说明」。仓库快照见 [docs/join.md](docs/join.md)。

另一进程调用：

```bash
python3 -m sunny_client --skill collect.strategy.query --slots '{"mission_name":"living_room"}'
```

```bash
python3 -m pytest -q
python3 scripts/validate_card.py cards/aidata.hermes.sample.json
```

## 一期范围

| 项 | 现状 |
|----|------|
| 首批租户 | `aidata.hermes`（Hub 填入 + sidecar 挂上）+ 演示对等 `lab.inspector` |
| 对外技能 | `collect.strategy.query`（进程内枚举）、`collect.volume.query`（无 AIDATA 包装器则 `ready=false`）。映射文件可把技能接到本地 handler 或下游 HTTP；invoke 按 Card `input_schema` 校验槽 |
| 发现 | 已登记且 `discovery=registered_peers` 可互发现；`restricted` / 写技能不出目录；升版后旧票作废 |
| 调用身份 | Agent 服务账号；不进个人 scratch |
| 管理台 | 管理员/开发者登录；Explore / Card / 编辑 / 变更历史 / 调用关系 / 活动（搜索·出票·调用可按 trace_id 对账） / Publish / 账号 |
| 权限 | 管理员全权限；开发者看名片、发布自己的智能体，且只能改/删自己创建的卡 |
| 第二户 | ChatBI 意向保留；八字段表搁置 |

## 文档

- [文档地图](docs/README.md)
- [给其他 Agent 的接入说明](docs/join.md)
- [Join Packet 规格](docs/specs/join.md)
- [Registry API](docs/specs/registry-api.md)
- [Adapter + Client](docs/specs/adapter.md)
- [开写前五件事](docs/decisions/ADR-001-开写前五件事.md)
- [Card 规格](docs/specs/sunny-card.md)
