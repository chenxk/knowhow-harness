# Agent 工程：长期记忆

Knowhow 的跨会话事实记忆在 `src/knowhow/memory.py`，默认 SQLite 路径 `KNOWHOW_MEMORY_PATH`（`.knowhow/memory.sqlite`）。

与 RAG 语料 `data/corpus/`、会话消息 JSON（`sessions.py`）分离：记忆只存原子事实，不把整段聊天写进语料。

状态：
- **pending**：自动抽取先写入；默认不参与回答召回。
- **active**：开跑前 Top-K 注入 decide/respond。

晋升路径：显式「请记住：…」、同一事实重复达到 `KNOWHOW_MEMORY_PROMOTE_HITS`（默认 2）、或侧栏「确认记住」。抽取发生在每轮对话结束；切换或新建会话不再 consolidate。

维护：每轮抽取先对照相关的 pending 与 active。没有可合并旧条则 add；同一件事改口（例如地点从上海改为杭州）update 原行并保留 status；用户说「忘掉」「不要记住」或「别记了」则 delete 最相似的一条；闲聊、重复和一次性任务是 noop。召回时写入 `last_recalled_at`。Top-K 仍以相关度为主，相关度接近时近期用过的靠前。长期不用的 active 记忆不会被自动删除。

自学入口：问「教我长期记忆怎么工作」（走 learn-agent skill）。
