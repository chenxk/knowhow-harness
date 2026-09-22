# Knowhow Harness

为自己日常使用的个人 Agent：本地工作台对话，会话可持久化，长期记忆、工具、Skills、RAG 与 Eval 都为真实可用性服务；配好密钥后 Langfuse 承接 trace 与反馈。

单用户、本机优先。不是多租户 SaaS，也没有鉴权与队列。默认 `KNOWHOW_MODE=offline`：不调用模型，进程内词法检索，工具是 `lookup_note` 的本地替身。`live` 才接 OpenAI 兼容模型和可选的 MCP 进程。

## 布局

```
src/knowhow/
  runtime.py     组装并执行一次提问
  graph/         decide → retrieve | act → respond
  policy.py      脚本路由 / 模型 JSON 路由
  respond.py     模板回答 / 模型回答
  rag/           markdown 入库与检索
  tools/         静态工具目录，或 MultiServerMCPClient
  skills.py      读取 skills/*/SKILL.md
  memory.py      长期事实记忆（SQLite）
  sessions.py    工作台会话 JSON 持久化
  evals/         golden.yaml 打分，可选写回 Langfuse
  observe/       Langfuse callback
  web/           FastAPI 工作台（主交互面）
servers/notes_mcp.py
data/corpus/     离线资料
evals/golden.yaml
```

从仓库根目录执行命令。`knowhow serve` 在 `http://127.0.0.1:8765` 打开工作台。回答通过 SSE 逐段推到页面。左侧会话列表与全文消息落在 `.knowhow/sessions/`（可用 `KNOWHOW_SESSIONS_DIR` 改路径），进程重启后仍可切换；标题默认截取首条用户消息。多轮追问会把最近 `KNOWHOW_HISTORY_TURNS`（默认 12）条消息交给路由和回答。长期记忆默认写在 `.knowhow/memory.sqlite`。

## 命令

```bash
uv sync --group dev
uv run knowhow serve
uv run knowhow run "如何重置密码"
uv run knowhow eval
uv run knowhow graph
uv run pytest
uv run ruff check src tests servers
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

`LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY` 都有值时，每次 `run` / `eval` 附带 Langfuse callback；`LANGFUSE_HOST` 指向你的 Langfuse 实例（自建或 cloud）。Eval 给有 trace id 的用例写 boolean score `case_pass`。工作台在回答下方提供「有用 / 没用」，写入 `user_feedback` score。

## 边界

检索是进程内词法相似度，存储接口在 `VectorStore`。LangGraph checkpoint 仍用内存，进程退出即丢；工作台会话消息另有 JSON 持久化，冷启动会回填最近对话再跑图。Eval 核对动作、来源和工具名，还没有 RAGAS。没有鉴权、队列和多租户。
