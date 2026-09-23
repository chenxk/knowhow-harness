# Agent 工程：工具与 Skills

工具目录在 `src/knowhow/tools/catalog.py`。内置 `current_time`、`lookup_note`、`learn_agent` 始终可用。聊天页设置里添加的 MCP 写在 `.knowhow/mcp.json`，启用后追加进目录；与内置重名时加服务名前缀。`KNOWHOW_MCP_ENABLED=true` 时还会合并 `config/mcp.yaml`。

Skills 在仓库 `skills/*/SKILL.md`：frontmatter 声明 name / description / tool / triggers；正文只在选中后作为 `Decision.guidance` 交给回答（`skills.py`）。

offline 路由 `ScriptedDecider`（`policy.py`）顺序：问题里出现工具名 → skill triggers →（有 active 记忆则直接 answer）→ 语料检索 → answer。

live 时 `ModelDecider` **同样先走** `match_known_tool_or_skill`（工具名 / skill triggers 优先），未命中才把目录写进路由器 system prompt 让模型输出 JSON。这样「教我长期记忆怎么工作」在 live 也会稳定进 `learn_agent`，不依赖模型是否选 tool。
