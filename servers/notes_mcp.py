"""Stdio MCP server that exposes one note lookup tool.

Run from the repo root:

    uv run python servers/notes_mcp.py
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("knowhow-notes")

_NOTES = {
    "oncall": "Page the runtime owner, then open the Langfuse trace for that thread id.",
    "password": "Password resets are confirmed with an email code. Old sessions are revoked.",
}


@mcp.tool()
def lookup_note(topic: str) -> str:
    """Look up a short operational note by topic."""
    key = topic.strip().lower()
    for name, text in _NOTES.items():
        if name in key:
            return text
    return "no note for that topic"


@mcp.tool()
def current_time() -> str:
    """Return the current local time with a numeric UTC offset."""
    from datetime import datetime

    clock = datetime.now().astimezone().isoformat(timespec="seconds")
    return f"当前时间：{clock}"


@mcp.tool()
def learn_agent(topic: str = "") -> str:
    """Return a short Agent-engineering coach primer for the given topic."""
    folded = topic.lower()
    lab = (
        "实验：请记住→active；只说事实→pending；再说一次或侧栏确认→active。"
        "对照 memory.py 与侧栏。"
    )
    if any(key in folded for key in ("记忆", "memory", "pending", "active")):
        return f"【课 1 · 长期记忆】pending→active；与 RAG/会话分离。{lab}"
    if any(key in folded for key in ("上下文", "context", "会话", "history")):
        return (
            "【课 2 · 上下文】sessions.py 持久化；"
            "KNOWHOW_HISTORY_TURNS 注入 decide/respond。"
        )
    if any(key in folded for key in ("工具", "skill", "tool", "mcp")):
        return (
            "【课 3 · 工具与 Skills】catalog.py + skills/*/SKILL.md；"
            "offline 先工具名再 triggers 再检索。"
        )
    return (
        "【学习模式】日常聊天照常；说「教我…」进入教练。"
        f"三课：记忆 / 上下文 / 工具与 Skills。{lab}"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
