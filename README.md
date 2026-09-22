# Knowhow Harness

为自己日常使用的个人 Agent：本地 Web UI 对话，会话可持久化，长期记忆、工具、Skills、RAG 与 Eval 都为真实可用性服务；配好密钥后 Langfuse 承接 trace 与反馈。

单用户、本机优先。不是多租户 SaaS，也没有鉴权与队列。默认 `KNOWHOW_MODE=offline`：不调用模型，进程内词法检索，工具是 `lookup_note` 的本地替身。`live` 才接 OpenAI 兼容模型和可选的 MCP 进程。

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
data/corpus/         离线资料
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

`KNOWHOW_MCP_ENABLED=true` 时，工具改为拉起 `config/mcp.yaml` 里的 stdio 服务，而不是内置 `lookup_note`。

`LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY` 都有值时，每次 `run` / `eval` 附带 Langfuse callback；`LANGFUSE_HOST` 指向你的 Langfuse 实例（自建或 cloud）。Eval 给有 trace id 的用例写 boolean score `case_pass`。UI 在回答下方提供「有用 / 没用」，写入 `user_feedback` score。

## 边界

检索是进程内词法相似度，存储接口在 `VectorStore`。LangGraph checkpoint 仍用内存，进程退出即丢；会话消息另有 JSON 持久化，冷启动会回填最近对话再跑图。跨会话事实记忆在独立 SQLite，与 RAG 语料分离。Eval 核对动作、来源、工具名和可选答案片段，还没有 RAGAS。没有鉴权、队列和多租户。
