# SUNNY Adapter + Client（M2）

| 项 | 内容 |
|----|------|
| 首租户 | `aidata.hermes` sidecar，不改 Hermes 内核 |
| 对外技能 | `collect.strategy.query`（本进程枚举）、`collect.volume.query`（有 AIDATA 包装器才 count） |
| 调用 | Client 向 Registry 搜卡、拿短时票，**直打 sidecar**。Registry 不转发 |

## 进程

```text
sunny-client（另一进程）
  → Registry search(skill)
  → Registry tickets
  → POST http://127.0.0.1:8091/sunny/invoke/<skill>
       Authorization: Bearer <ticket>
  → sidecar 向 Registry verify 票
  → 本地执行；不上报 SQL / 预览图 / DSL
  → Client 可选 POST /invocations 记一笔边
```

## 环境变量

| 变量 | 默认 | 用途 |
|------|------|------|
| `SUNNY_REGISTRY_URL` | `http://127.0.0.1:8088` | 本机连 Registry；跨机改成握手包里的基址 |
| `SUNNY_ADAPTER_HOST` | `0.0.0.0` | sidecar 监听 |
| `SUNNY_ADAPTER_PUBLIC_URL` | 局域网 IP + `:8091/sunny/v1` | 写入 Card 的对外接口，不会是 `0.0.0.0` |
| `SUNNY_ADAPTER_CARD` | `cards/aidata.hermes.sample.json` | 挂上时用的名片 |
| `SUNNY_ADAPTER_KEY_FILE` | `data/adapter-keys/<agent_id>.key` | sidecar 自己的 `sak_` |
| `SUNNY_ADMIN_TOKEN` / `SUNNY_ENROLL_TOKEN` | `sunny-dev-*` | 409 后签发 key / 首次自注册 |
| `AIDATA_ROOT` | `~/PycharmProjects/AIDataAgent` | 有 `es_query_ai_collect.py` 才真 count |

Hub 已登记同一 `agent_id` 时，sidecar **只挂接口、不改 enrollment_source**（仍是 `hub`）。

## 启动

先 Registry，再 sidecar：

```bash
python3 -m sunny_registry
python3 -m sunny_adapter
```

Sidecar 启动时会：

1. 用 enroll token 自注册；若 Hub 已登记过同一 `agent_id`，管理员签发一把新 key 再挂上
2. 把 Card 里的 `supportedInterfaces[0].url` 改成 `SUNNY_ADAPTER_PUBLIC_URL`
3. 按 `SUNNY_ADAPTER_HEARTBEAT_S` 心跳

钥匙写在 `data/adapter-keys/<agent_id>.key`，不进 Card、不进 Git。

## 另一进程调用

```bash
python3 -m sunny_client --skill collect.strategy.query --slots '{"mission_name":"living_room"}'
```

环境变量：`SUNNY_REGISTRY_URL`、`SUNNY_AGENT_KEY`（调用方）、`SUNNY_ADMIN_TOKEN`（本地可代签票）、`SUNNY_CALLER_ID`（管理员代签时的 caller，默认 `lab.inspector`）。

## 余量查询

未配置 AIDataAgent 包装器时：`ready=false` `mock=true` `count=0`，**仍然算 M2 调通**（票验过、槽校验过、没有泄 DSL）。  
设置 `AIDATA_ROOT` 且本机 `AIDATA_*` 代理可用时，sidecar 才对 `ai_collect` 做 count。
