# Agent 工程：工具与 Skills

工具目录在 `src/knowhow/tools/catalog.py`。默认 offline 提供 `current_time`、`lookup_note`、`learn_agent`；`KNOWHOW_MCP_ENABLED=true` 时改为 `config/mcp.yaml` 里的 MCP 进程（如 `servers/notes_mcp.py`）。

Skills 在仓库 `skills/*/SKILL.md`：frontmatter 声明 name / description / tool / triggers；正文只在选中后作为 `Decision.guidance` 交给回答（`skills.py`）。

offline 路由 `ScriptedDecider`（`policy.py`）顺序：问题里出现工具名 → skill triggers →（有 active 记忆则直接 answer）→ 语料检索 → answer。

live 时 `ModelDecider` 把工具名与技能目录写进路由器 system prompt，模型输出 JSON action。
