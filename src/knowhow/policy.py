"""Choose retrieve, tool, or answer before the graph branches."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from knowhow.rag.store import VectorStore
from knowhow.tools.catalog import ToolCatalog
from knowhow.types import Decision, message_text

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)

_ROUTER_SYSTEM = """你是运行时路由器。只输出一个 JSON 对象，不要输出其它文字。
字段：
- action: retrieve、tool、answer 之一
- query: 用于检索或工具的短查询
- tool_name: action 为 tool 时必须是可用工具名，否则空字符串
- tool_args: 字符串到字符串的对象。调用 lookup_note 时带 topic
可用工具：{tools}
"""


class Chat(Protocol):
    """Subset of a LangChain chat model this runtime calls."""

    async def ainvoke(self, messages: list[SystemMessage | HumanMessage]) -> AIMessage:
        """Return the next assistant message."""

    def astream(self, messages: list[SystemMessage | HumanMessage]) -> AsyncIterator[AIMessage]:
        """Yield assistant message chunks."""


class Decider(Protocol):
    """Map a user question to the next graph branch."""

    async def decide(self, question: str) -> Decision:
        """Return the branch and any tool arguments."""


class ScriptedDecider:
    """Offline router: a known tool name wins, then a retrieval score, then answer."""

    def __init__(self, store: VectorStore, catalog: ToolCatalog, *, threshold: float) -> None:
        self._store = store
        self._catalog = catalog
        self._threshold = threshold

    async def decide(self, question: str) -> Decision:
        for name in self._catalog.names():
            if name in question:
                topic = question.replace(name, "").strip(" :：") or question
                return Decision(
                    action="tool",
                    query=topic,
                    tool_name=name,
                    tool_args={"topic": topic},
                )
        hits = self._store.search(question, k=1)
        if hits and hits[0].score >= self._threshold:
            return Decision(action="retrieve", query=question)
        return Decision(action="answer", query=question)


class ModelDecider:
    """Ask the chat model for a JSON decision. Invalid JSON becomes `answer`."""

    def __init__(self, chat: Chat, catalog: ToolCatalog) -> None:
        self._chat = chat
        self._catalog = catalog

    async def decide(self, question: str) -> Decision:
        tools = ", ".join(self._catalog.names()) or "(none)"
        message = await self._chat.ainvoke(
            [
                SystemMessage(content=_ROUTER_SYSTEM.format(tools=tools)),
                HumanMessage(content=question),
            ]
        )
        return parse_decision(
            message_text(message.content),
            question=question,
            tool_names=set(self._catalog.names()),
        )


def parse_decision(text: str, *, question: str, tool_names: set[str]) -> Decision:
    """Parse router JSON. Bad payloads and unknown tools fall back to answer."""
    raw = _FENCE.sub("", text.strip()).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Decision(action="answer", query=question)
    if not isinstance(data, dict):
        return Decision(action="answer", query=question)
    action = data.get("action", "answer")
    if action not in ("retrieve", "tool", "answer"):
        return Decision(action="answer", query=question)
    query = str(data.get("query") or question)
    tool_name = str(data.get("tool_name") or "")
    tool_args = _string_args(data.get("tool_args"))
    if action == "tool":
        if tool_name not in tool_names:
            return Decision(action="answer", query=question)
        tool_args.setdefault("topic", query)
    else:
        tool_name = ""
        tool_args = {}
    return Decision(action=action, query=query, tool_name=tool_name, tool_args=tool_args)


def _string_args(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
