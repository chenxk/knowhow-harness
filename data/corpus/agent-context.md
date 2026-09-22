# Agent 工程：上下文与会话

一次提问走 LangGraph：`graph/` 里 decide → retrieve | act → respond（见 `graph/builder.py`）。

多轮对话：最近 `KNOWHOW_HISTORY_TURNS`（默认 12）条消息交给 decide 与 respond（`policy.py` / `respond.py`）。短追问时 offline 路由会用上一轮用户话扩展探测串（`_followup_probe`）。

会话列表与全文消息落在 `KNOWHOW_SESSIONS_DIR`（默认 `.knowhow/sessions/`），由 `sessions.py` 读写；LangGraph 的 MemorySaver checkpoint 仍是进程内，退出即丢。

冷启动会回填最近对话再跑图。这与长期记忆（`memory.py`）是两条线。
