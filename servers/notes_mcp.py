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


if __name__ == "__main__":
    mcp.run(transport="stdio")
