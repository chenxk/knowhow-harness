# Knowhow Harness

个人可用的本地 Agent，也是学习 Agent 工程（上下文、记忆、工具/Skills、eval、观测）的工作台，定位为：可自述的 Agent 工程工作台：日常聊天是默认；想学时通过 Skill 进入学习模式。

单用户、本机优先。不是多租户 SaaS，也没有鉴权与队列。默认 `KNOWHOW_MODE=offline`：不调用模型，进程内词法检索，工具是本地静态目录。`live` 才接 OpenAI 兼容模型和可选的 MCP 进程。

## 学习模式

直接聊天照常。问「教我长期记忆怎么工作」「学习 agent」等会命中 `skills/learn-agent/`，用本仓库模块当教材（优先实验，少空讲）。

三课大纲：

1. **长期记忆** — `memory.py` pending→active、「请记住」/重复/侧栏确认
2. **上下文 / 会话** — `sessions.py` + `KNOWHOW_HISTORY_TURNS` 注入 decide/respond
3. **工具与 Skills** — `tools/catalog.py` + `skills/*/SKILL.md`、offline 路由顺序

语料提纲在 `data/corpus/agent-*.md`。扩展阅读：Eval / Langfuse 见 `agent-eval-observe.md`。

## 布局

```
frontend/            Vite + React SPA（主 UI）
src/knowhow/
  runtime.py         组装并执行一次提问
  graph/             decide → retrieve | act → respond
  policy.py          脚本路由 / 模型 JSON 路由
  respond.py         模板回答 / 模型回答
  rag/               markdown 入库与检索
  tools/             静态工具目录，或 MultiServerMCPClient
  skills.py          读取 skills/*/SKILL.md
  memory.py          长期事实记忆（SQLite）
  sessions.py        会话 JSON 持久化
  evals/             golden.yaml 打分，可选写回 Langfuse
  observe/           Langfuse callback
  web/               FastAPI `/api` + 挂载 static SPA
  web/static/        `pnpm --dir frontend build` 产物
  web/index.html     无 static 时的遗留回退页
servers/notes_mcp.py
skills/              SKILL.md（含 learn-agent 学习模式）
data/corpus/         离线资料（含 agent-*.md 工程提纲）
evals/golden.yaml
```

从仓库根目录执行命令。`knowhow serve` 在 `http://127.0.0.1:8765` 同时提供 API 与 UI（需先 `pnpm --dir frontend build`）。开发时可用 Vite：`pnpm --dir frontend dev`（代理 `/api` → `:8765`）。回答通过 SSE 逐段推到页面。左侧会话列表与全文消息落在 `.knowhow/sessions/`（可用 `KNOWHOW_SESSIONS_DIR` 改路径），进程重启后仍可切换；标题默认截取首条用户消息。多轮追问会把最近 `KNOWHOW_HISTORY_TURNS`（默认 12）条消息交给路由和回答。长期记忆默认写在 `.knowhow/memory.sqlite`（`KNOWHOW_MEMORY_PATH`）：自动抽取进 **pending**，说「请记住：…」、同一事实重复达到 `KNOWHOW_MEMORY_PROMOTE_HITS`（默认 2）、或侧栏点「确认记住」后升为 **active**（仅 active 参与回答召回）；切换/新建会话会 consolidate。侧栏可列表/删除/确认；记忆不进 `data/corpus`。

## 命令

```bash
uv sync --group dev
pnpm --dir frontend install
pnpm --dir frontend build
uv run knowhow serve
uv run knowhow run "如何重置密码"
uv run knowhow eval
uv run knowhow graph
uv run pytest
uv run ruff check src tests servers
```

前端开发（另开终端跑 `knowhow serve`）：

```bash
pnpm --dir frontend dev
```

`eval` 有失败用例时退出码为 1。

## Live

```bash
set KNOWHOW_MODE=live
set OPENAI_API_KEY=...
set OPENAI_BASE_URL=https://api.deepseek.com
set KNOWHOW_CHAT_MODEL=deepseek-chat
```

`KNOWHOW_MCP_ENABLED=true` 时，工具改为拉起 `config/mcp.yaml` 里的 stdio 服务，而不是内置静态工具。

`LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY` 都有值时，每次 `run` / `eval` 附带 Langfuse callback；`LANGFUSE_HOST` 指向你的 Langfuse 实例（自建或 cloud）。Eval 给有 trace id 的用例写 boolean score `case_pass`。UI 在回答下方提供「有用 / 没用」，写入 `user_feedback` score。

## 边界

检索是进程内词法相似度，存储接口在 `VectorStore`。LangGraph checkpoint 仍用内存，进程退出即丢；会话消息另有 JSON 持久化，冷启动会回填最近对话再跑图。跨会话事实记忆在独立 SQLite，与 RAG 语料分离。Eval 核对动作、来源、工具名和可选答案片段，还没有 RAGAS。没有鉴权、队列和多租户。
