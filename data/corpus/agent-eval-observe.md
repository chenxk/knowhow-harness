# Agent 工程：Eval 与观测

离线黄金集在 `evals/golden.yaml`，由 `knowhow eval` 或 Web 侧栏评测按钮跑；断言动作、来源、工具名、可选答案/记忆片段。改路由或语料时同步改它。

Langfuse：`LANGFUSE_PUBLIC_KEY` 与 `LANGFUSE_SECRET_KEY` 都有值时，`observe/` 为每次 run/eval 挂 callback。Eval 可写 boolean score `case_pass`；UI「有用/没用」写 `user_feedback`。

评测只消费 `Runtime.run` 的结果，不把规则写进图节点（`evals/`）。
