# 第二户 lab.echo

| 项 | 内容 |
|----|------|
| 状态 | 已落地 |
| 回声进程 | `python3 -m sunny_echo`，默认 `:8092` |
| sidecar | 第二条 adapter，默认 `:8093` |
| 名片 | [`../../cards/lab.echo.sample.json`](../../cards/lab.echo.sample.json) |
| 映射 | [`../../sunny_adapter/mappings/lab.echo.json`](../../sunny_adapter/mappings/lab.echo.json) |

本仓真 HTTP 回声，用来证明 Hub 不是一户自嗨。Registry **不转发**业务；调用方搜卡、拿票、直打 echo sidecar。

## 技能

| skill | 档位 | 对等 |
|-------|------|------|
| `echo.ping` | `read` / `internal` | 可搜、可出票、可调 |
| `echo.secret` | `read` / `restricted` | 搜不到、出票 403；`GET /extended` 看得到 |

## 进程

```text
python3 -m sunny_echo          # :8092  GET /health  POST /v1/echo
ECHO_URL=http://127.0.0.1:8092 \
SUNNY_ADAPTER_CARD=cards/lab.echo.sample.json \
SUNNY_ADAPTER_MAPPING=sunny_adapter/mappings/lab.echo.json \
SUNNY_ADAPTER_AGENT_ID=lab.echo \
SUNNY_ADAPTER_PORT=8093 \
SUNNY_ADAPTER_PUBLIC_URL=http://127.0.0.1:8093/sunny/v1 \
python3 -m sunny_adapter
```

不要和 `aidata.hermes` 的 `:8091` 抢端口。sidecar well-known 仍挂完整 SUNNY Card，给 Registry `pull`。

## 联测

```bash
python3 -m sunny_client --skill echo.ping --slots '{"query":"hello"}'
```

调用方用非 Hermes 身份（`lab.inspector` 的 `sak_` 或管理员代签）。期望 `ready=true` 且回声 `query`。
