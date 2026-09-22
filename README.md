# Knowhow Harness

生产形态的 Agent Runtime 骨架：LangGraph 负责分支，MCP 提供工具，RAG 提供资料，Eval 用黄金集打分，Langfuse 在配了密钥后接收 trace。

当前默认 `KNOWHOW_MODE=offline`。不调用模型，进程内词法检索，工具是 `lookup_note` 的本地替身。`live` 才接 OpenAI 兼容模型和可选的 MCP 进程。

## 布局

```
src/knowhow/
  runtime.py     组装并执行一次提问
  graph/         decide → retrieve | act → respond
  policy.py      脚本路由 / 模型 JSON 路由
  respond.py     模板回答 / 模型回答
  rag/           markdown 入库与检索
  tools/         静态工具目录，或 MultiServerMCPClient
  evals/         golden.yaml 打分，可选写回 Langfuse
  observe/       Langfuse callback
servers/notes_mcp.py
data/corpus/     离线资料
evals/golden.yaml
```

从仓库根目录执行命令。

## 命令

```bash
uv sync --group dev
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

`LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY` 都有值时，每次 `run` / `eval` 附带 Langfuse callback。Eval 只给已经产生 trace id 的用例写 `case_pass`。

## 边界

检索是进程内词法相似度，存储接口在 `VectorStore`。Checkpoint 用内存，进程退出即丢。Eval 核对动作、来源和工具名，还没有 RAGAS。没有鉴权、队列和多租户。
