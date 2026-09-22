# Agent 工程：长期记忆

Knowhow 的跨会话事实记忆在 `src/knowhow/memory.py`，默认 SQLite 路径 `KNOWHOW_MEMORY_PATH`（`.knowhow/memory.sqlite`）。

与 RAG 语料 `data/corpus/`、会话消息 JSON（`sessions.py`）分离：记忆只存原子事实，不把整段聊天写进语料。

状态：
- **pending**：自动抽取先写入；默认不参与回答召回。
- **active**：开跑前 Top-K 注入 decide/respond。

晋升路径：显式「请记住：…」、同一事实重复达到 `KNOWHOW_MEMORY_PROMOTE_HITS`（默认 2）、或侧栏「确认记住」。切换/新建会话会 consolidate。

自学入口：问「教我长期记忆怎么工作」（走 learn-agent skill）。
