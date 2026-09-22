"""Values that cross the runtime, graph, and eval seams."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Action = Literal["retrieve", "tool", "answer"]


class Decision(BaseModel):
    """Router output. `tool_args` values stay strings so checkpoints stay plain JSON."""

    action: Action
    query: str = ""
    tool_name: str = ""
    tool_args: dict[str, str] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """One user or assistant turn stored on a thread."""

    role: Literal["user", "assistant"]
    content: str


class StreamEvent(BaseModel):
    """One server-sent event while an answer is being produced."""

    type: Literal["status", "delta", "done"]
    text: str = ""
    action: Action = "answer"
    sources: list[str] = Field(default_factory=list)
    tool_name: str = ""
    trace_id: str | None = None
    answer: str = ""


class RunResult(BaseModel):
    """One graph invocation, including the fields eval checks."""

    answer: str
    action: Action
    sources: tuple[str, ...] = ()
    tool_name: str = ""
    trace_id: str | None = None


def message_text(content: str | list[str | dict[str, Any]]) -> str:
    """Flatten a chat message body to text."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(str(block.get("text", "")))
    return "".join(parts)
