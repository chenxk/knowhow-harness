# AGENTS.md

Knowhow Harness 是一个个人可用的本地 Agent Runtime。命令从仓库根目录执行。

## 模块

| 路径 | 职责 |
|------|------|
| `runtime.py` | 读取配置、建索引、编译图、执行一次提问 |
| `graph/` | LangGraph：`decide` 之后走 `retrieve`、`act` 或直接 `respond` |
| `policy.py` | 路由。offline 用脚本，live 用模型 JSON |
| `respond.py` | 最终回答 |
| `rag/` | 语料切块和 `VectorStore` |
| `memory.py` | 跨会话原子事实记忆（SQLite）。与 checkpoint / RAG 语料分离 |
| `tools/` | `ToolCatalog`。默认静态目录；`KNOWHOW_MCP_ENABLED=true` 时改走 MCP |
| `skills.py` | 读取仓库 `skills/*/SKILL.md`。选中后才把正文交给回答 |
| `evals/` | 只消费 `Runtime.run` 的结果，不把规则写进图节点 |
| `observe/` | Langfuse callback 与 score 写入。两个密钥都缺省时不创建 client |
| `web/` | FastAPI：`/api/*` + 生产态挂载 `web/static` SPA；无 `static/` 时回退 `index.html` |
| `sessions.py` | 会话列表与消息 JSON 持久化、自动标题 |
| `servers/` | 独立 MCP 进程，不 import `knowhow` |
| `frontend/` | Vite + React SPA（主 UI）。`pnpm dev` 代理 `/api`；`pnpm build` 输出到 `web/static` |

## 约定

- 配置进 `Settings`。`live` 缺 `OPENAI_API_KEY`、MCP 配置缺失、语料目录缺失，都在 `Settings.check()` 失败。
- 模型输出的路由 JSON 在 `parse_decision` 校验。非法 JSON 或未知工具名退回 `answer`。
- 图的状态字段保持可序列化的普通值，不把连接或 client 放进 state。
- 离线黄金集在 `evals/golden.yaml`。改路由或语料时同步改它，并跑 `uv run pytest`。
- 用户可见的 CLI 文案用中文。代码标识符用英文。
- 会话默认写在 `KNOWHOW_SESSIONS_DIR`（默认 `.knowhow/sessions/`）。多轮把最近 `KNOWHOW_HISTORY_TURNS`（默认 12）条消息交给 decide/respond。
- 长期记忆默认落在 `KNOWHOW_MEMORY_PATH`（`.knowhow/memory.sqlite`）。开跑前 Top-K 注入 decide/respond；回合结束后异步抽取（`请记住` 同步写入）。只存原子事实，不把整段聊天当记忆，也不写入 `data/corpus`。
- 改 UI：在 `frontend/` 用 `pnpm`；生产构建进 `src/knowhow/web/static/`，由 `knowhow serve` 在 `/` 提供。
