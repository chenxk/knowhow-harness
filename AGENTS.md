# AGENTS.md

Knowhow Harness 是一个 Agent Runtime 演示骨架。命令从仓库根目录执行。

## 模块

| 路径 | 职责 |
|------|------|
| `runtime.py` | 读取配置、建索引、编译图、执行一次提问 |
| `graph/` | LangGraph：`decide` 之后走 `retrieve`、`act` 或直接 `respond` |
| `policy.py` | 路由。offline 用脚本，live 用模型 JSON |
| `respond.py` | 最终回答 |
| `rag/` | 语料切块和 `VectorStore` |
| `tools/` | `ToolCatalog`。默认静态目录；`KNOWHOW_MCP_ENABLED=true` 时改走 MCP |
| `skills.py` | 读取仓库 `skills/*/SKILL.md`。选中后才把正文交给回答 |
| `evals/` | 只消费 `Runtime.run` 的结果，不把规则写进图节点 |
| `observe/` | Langfuse。两个密钥都缺省时不创建 client |
| `web/` | 测试台。进程内复用一个 `Runtime`，页面只调 HTTP |
| `servers/` | 独立 MCP 进程，不 import `knowhow` |

## 约定

- 配置进 `Settings`。`live` 缺 `OPENAI_API_KEY`、MCP 配置缺失、语料目录缺失，都在 `Settings.check()` 失败。
- 模型输出的路由 JSON 在 `parse_decision` 校验。非法 JSON 或未知工具名退回 `answer`。
- 图的状态字段保持可序列化的普通值，不把连接或 client 放进 state。
- 离线黄金集在 `evals/golden.yaml`。改路由或语料时同步改它，并跑 `uv run pytest`。
- 用户可见的 CLI 文案用中文。代码标识符用英文。
