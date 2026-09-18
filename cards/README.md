# 样例名片

| 文件 | Agent | 状态 |
|------|-------|------|
| [`aidata.hermes.sample.json`](./aidata.hermes.sample.json) | AI 数据智能体 | 两技能已评审；空库 seed 时按 Hub 填入登记 |
| [`lab.inspector.sample.json`](./lab.inspector.sample.json) | 演示对等 Agent | 空库 seed 时按 Agent 主动注册 |

校验：

```bash
python3 scripts/validate_card.py cards/aidata.hermes.sample.json
```

约定：

- URL 一律用 `*.internal.example` 占位，不写现网主机
- 对外技能以 Card 为准，不以 Hermes 内部 Skill 全集为准
- ChatBI 名片搁置，不在这里先登记
