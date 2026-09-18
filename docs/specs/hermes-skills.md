# Hermes 侧 `sunny.discover` / `sunny.invoke`

| 项 | 内容 |
|----|------|
| 位置 | 逻辑在本仓 `sunny_client/hermes.py`；Chat 入口在 AIDataAgent `skills/hermes/sunny-*` |
| 默认 | **关闭**。不改 Hermes 内核，不写入 `SOUL.md` |
| 调用 | Registry 搜卡 / 出票后 **直打对方 sidecar**，Registry 不转发 |

立项 §5.2：可选 Skill，默认关闭。图像 / 闭环 Chat 路由仍写死在本机适配器，不经 SUNNY。

## 打开方式

同时满足：

1. 环境变量 `AIDATA_SUNNY=1`（或 `SUNNY_HERMES_SKILLS=1`）
2. 重新执行 `AIDATA_SUNNY=1 bash skills/scripts/sync-to-hermes.sh`，才会把 SKILL.md 同步进 Hermes 技能树
3. `SUNNY_AGENT_KEY` 为 **Agent 服务账号**（`sak_`）。也可用 `SUNNY_AGENT_KEY_FILE` 指向服务文件

禁止：把 key 写进 `~/.hermes/scratch/`、名片、回复、观测事件。

| 变量 | 默认 | 用途 |
|------|------|------|
| `AIDATA_SUNNY` / `SUNNY_HERMES_SKILLS` | 关 | 技能开关 |
| `SUNNY_REGISTRY_URL` | `http://127.0.0.1:8088` | 目录基址 |
| `SUNNY_AGENT_KEY` | 空 | 调用方服务 key |
| `SUNNY_AGENT_KEY_FILE` | 空 | 读 key 的服务文件；路径含 `scratch` 会拒 |
| `SUNNY_CALLER_ID` | `aidata.hermes` | 自调用检测用的本机 `agent_id` |
| `SUNNY_ROOT` | `~/PycharmProjects/Sunny` | AIDataAgent 适配器把本仓挂进 `sys.path` |

## 行为

| Skill | 做什么 | 不做什么 |
|-------|--------|----------|
| `sunny.discover` | 按 `skill` / `tag` / `q` / `workspace` 搜目录，或按 `agent_id` 读一张卡的摘要 | 不返回接口 URL、票、key；看见名片 ≠ 能调用 |
| `sunny.invoke` | 按 **skill id** 出票并直打对等 sidecar | 不调自己；不调本机图像/闭环/知识/场景库技能；不整段转发对话 |

本机硬编码、禁止经 `sunny.invoke` 的前缀：`es.` / `es-`、`cvat.` / `cvat-`、`kb.`、`db.`、`image.`、`memory.`、`html.`、`label.`、`session.`、`pet.`、`aidata.`、`sunny.`、`working-`。点号 id 与 Hermes 目录名（如 `es-query-ai-collect`）都拒，大小写不敏感。

`callee_id == SUNNY_CALLER_ID`（默认自己）→ `ready=false`，避免 Chat → Registry → 本机 sidecar 绕回。

输出统一带 `ready` / `mock` / `items` / `result` / `meta`。票只留 `_ticket.jti` 与 `callee_id`。

## 本机入口

```bash
# 仍关闭：ready=false，不访问网络
python3 -m sunny_client.hermes discover --skill collect.strategy.query

# 打开后（对等身份，不要用自己调自己）
AIDATA_SUNNY=1 SUNNY_AGENT_KEY=sak_… \
  python3 -m sunny_client.hermes invoke \
    --skill some.peer.query \
    --slots '{}' \
    --callee other.agent
```

AIDataAgent 仓库根（适配器默认关）：

```bash
python3 skills/adapters/sunny_discover.py --skill some.peer.query
python3 skills/adapters/sunny_invoke.py --skill some.peer.query --slots '{}'
```

## 验收

1. 未设 `AIDATA_SUNNY` 时两条 Skill 都是 `ready=false`，且默认 `sync-to-hermes.sh` **不拷** 这两份 SKILL.md
2. 打开后能搜到已登记对等 Agent，摘要不含 key / URL
3. `sunny.invoke` 调 `es.query_ai_collect` / `cvat.create_special_task` / `kb.retrieve` 被拒
4. 以 `aidata.hermes` 为 caller 再调 `aidata.hermes` 被拒
5. 另一进程（如 `lab.inspector`）仍可用 `sunny_client` 调通 `collect.strategy.query`（不经过这两条 Chat Skill 也行）
