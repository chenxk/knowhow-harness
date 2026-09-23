"""Offline-friendly coach text for the learn_agent tool."""

from __future__ import annotations

_MEMORY_LAB = """实验（推荐先做）：
1. 新开会话，说「请记住：我喜欢喝绿茶」→ 侧栏应出现 active 记忆。
2. 再开会话只说「我叫阿花」（不说请记住）→ 侧栏 pending，回答尚不召回。
3. 再说一次「我叫阿花」，或点「确认记住」→ 升为 active；新会话问「我叫什么」应能答出。
对照：`memory.py`、`tests/test_memory.py`、侧栏确认记住。"""


def learn_agent_text(topic: str = "") -> str:
    """Return a short Chinese primer keyed by the user topic."""
    folded = topic.lower()
    if any(key in folded for key in ("记忆", "memory", "pending", "active", "请记住")):
        return "\n".join(
            [
                "【课 1 · 长期记忆】",
                "跨会话事实在 `memory.py`（SQLite），"
                "与 RAG 语料 `data/corpus/`、会话 JSON 分离。",
                "自动抽取先写 pending；仅 active 在开跑前注入 decide/respond。",
                "晋升：显式「请记住」、重复 ≥ KNOWHOW_MEMORY_PROMOTE_HITS、"
                "或侧栏确认。",
                "",
                _MEMORY_LAB,
            ]
        )
    if any(key in folded for key in ("上下文", "context", "会话", "history", "多轮")):
        return "\n".join(
            [
                "【课 2 · 上下文 / 会话】",
                "图状态在 `graph/`；多轮把最近 KNOWHOW_HISTORY_TURNS 条"
                "交给 decide/respond。",
                "会话列表与消息在 `sessions.py`（默认 `.knowhow/sessions/`），"
                "与 MemorySaver checkpoint 不同。",
                "追问时 offline 路由会用上一轮用户话扩展短问题"
                "（`policy._followup_probe`）。",
                "下一步可问「教我长期记忆怎么工作」做课 1 实验。",
            ]
        )
    if any(
        key in folded
        for key in ("工具", "skill", "skills", "tool", "mcp", "lookup")
    ):
        return "\n".join(
            [
                "【课 3 · 工具与 Skills】",
                "工具：`tools/catalog.py`（内置静态工具始终在；"
                "设置里的 MCP 写在 `.knowhow/mcp.json`，启用后追加）。",
                "Skills：`skills/*/SKILL.md`；选中后才把 body 交给回答"
                "（`skills.py` + Decision.guidance）。",
                "offline / live 都先走 `match_known_tool_or_skill`："
                "工具名 → skill triggers；未命中才检索或问模型。"
                "本 skill 的工具名就是 `learn_agent`。",
            ]
        )
    if any(key in folded for key in ("eval", "评测", "langfuse", "观测", "trace")):
        return "\n".join(
            [
                "【扩展 · Eval 与观测】",
                "黄金集：`evals/golden.yaml`，由 `knowhow eval` / UI 评测按钮跑。",
                "Langfuse：双密钥齐全时 callback 写 trace；"
                "eval 可写 `case_pass`，UI 可写 `user_feedback`。",
                "详见语料 `agent-eval-observe.md` 与 `observe/`。",
            ]
        )
    return "\n".join(
        [
            "【学习模式】Knowhow = 日常个人 Agent + Agent 工程教练。",
            "直接聊天照常；想学时说「教我…」或「学习 agent」进入本 skill。",
            "三课：1) 长期记忆 pending→active  "
            "2) 上下文/会话  3) 工具与 Skills。",
            "优先做实验、对着本仓库路径看代码，少背空概念。",
            "",
            "试试：「教我长期记忆怎么工作」",
            "",
            _MEMORY_LAB,
        ]
    )
