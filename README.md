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
servers/notes_mcp.py
skills/              SKILL.md（含 learn-agent 学习模式）
data/corpus/         离线资料（含 agent-*.md 工程提纲）
evals/golden.yaml
```

从仓库根目录执行命令。`knowhow serve` 在 `http://127.0.0.1:8765` 同时提供 API 与 UI（需先 `pnpm --dir frontend build`）。开发时可用 Vite：`pnpm --dir frontend dev`（代理 `/api` → `:8765`）。回答通过 SSE 逐段推到页面。左侧会话列表与全文消息落在 `.knowhow/sessions/`（可用 `KNOWHOW_SESSIONS_DIR` 改路径），进程重启后仍可切换；标题默认截取首条用户消息。多轮追问会把最近 `KNOWHOW_HISTORY_TURNS`（默认 12）条消息交给路由和回答。长期记忆默认写在 `.knowhow/memory.sqlite`（`KNOWHOW_MEMORY_PATH`）：每轮对话结束后自动抽取进 **pending**（live 会调模型），说「请记住：…」当轮同步写入 **active**，同一事实重复达到 `KNOWHOW_MEMORY_PROMOTE_HITS`（默认 2）或侧栏点「确认记住」后升为 **active**（仅 active 参与回答召回）。抽取会对照已有记忆：改口覆盖同一条并保留状态，说「忘掉 / 不要记住 / 别记了」则删掉最相似的一条，重复和闲聊不另起一条。召回时记下使用时间，相关度接近时最近用过的靠前；不会因为长期没用就自动删掉 active 记忆。点侧栏切换或新建会话不再整理、不再调模型。`KNOWHOW_MEMORY_CONSOLIDATE_ON_SWITCH` 默认关闭；只有显式打开时，直接调用 `POST /api/memories/consolidate` 才会再跑一遍抽取。侧栏可列表/删除/确认；记忆不进 `data/corpus`。

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

聊天页左侧栏左下角「设置」可以添加 MCP 服务，配置写在 `.knowhow/mcp.json`（已 gitignore）。支持 stdio（命令和参数）以及 URL（streamable HTTP 或 SSE）。保存后下一轮对话就能调用；停用的服务不注册工具；连不上时错误显示在设置里，内置工具仍可用。和内置工具重名时会加上服务名前缀。`KNOWHOW_MCP_ENABLED=true` 仍会额外合并 `config/mcp.yaml`。

`LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY` 都有值时，每次 `run` / `eval` 附带 Langfuse callback；`LANGFUSE_HOST` 指向你的 Langfuse 实例（自建或 cloud）。`LANGFUSE_PROJECT_ID` 有值时，解剖抽屉的「在 Langfuse 打开」指向该项目的 traces 搜索；缺省则不生成链接。Eval 给有 trace id 的用例写 boolean score `case_pass`。UI 在回答下方提供「有用 / 没用」，写入 `user_feedback` score。

## 边界

检索是进程内词法相似度，存储接口在 `VectorStore`。LangGraph checkpoint 仍用内存，进程退出即丢；会话消息另有 JSON 持久化，冷启动会回填最近对话再跑图。跨会话事实记忆在独立 SQLite，与 RAG 语料分离。Eval 核对动作、来源、工具名和可选答案片段，还没有 RAGAS。没有鉴权、队列和多租户。

## 许可证

[MIT](LICENSE)。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。
