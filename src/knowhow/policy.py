"""Choose retrieve, tool, or answer before the graph branches."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from knowhow.rag.store import VectorStore
from knowhow.skills import Skill, guidance_for
from knowhow.tools.catalog import ToolCatalog
from knowhow.types import ChatMessage, Decision, message_text

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)

_ROUTER_SYSTEM = """你是运行时路由器。只输出一个 JSON 对象，不要输出其它文字。
字段：
- action: retrieve、tool、answer 之一
- query: 用于检索或工具的短查询
- tool_name: action 为 tool 时必须是可用工具名，否则空字符串
- tool_args: 字符串到字符串的对象。调用 lookup_note 时带 topic
可用工具：{tools}
技能：{skills}
问到技能描述的事情时，action 用 tool，tool_name 用该技能的工具名。
用户个人偏好或档案类问题优先用 answer，并结合提供的长期记忆。
"""


class Chat(Protocol):
    """Subset of a LangChain chat model this runtime calls."""

    async def ainvoke(self, messages: list[SystemMessage | HumanMessage]) -> AIMessage:
        """Return the next assistant message."""

    def astream(self, messages: list[SystemMessage | HumanMessage]) -> AsyncIterator[AIMessage]:
        """Yield assistant message chunks."""


class Decider(Protocol):
    """Map a user question to the next graph branch."""

    async def decide(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[str] = (),
    ) -> Decision:
        """Return the branch and any tool arguments."""


class ScriptedDecider:
    """Offline router: a known tool name wins, then a skill trigger, then retrieval."""

    def __init__(
        self,
        store: VectorStore,
        catalog: ToolCatalog,
        skills: list[Skill],
        *,
        threshold: float,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._skills = skills
        self._threshold = threshold

    async def decide(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[str] = (),
    ) -> Decision:
        probe = _followup_probe(question, history)
        folded = probe.lower()
        for name in self._catalog.names():
            if name in question or name in probe:
                topic = probe.replace(name, "").strip(" :：") or probe
                args = {"topic": topic} if name in {"lookup_note", "learn_agent"} else {}
                return Decision(
                    action="tool",
                    query=topic,
                    tool_name=name,
                    tool_args=args,
                    guidance=guidance_for(name, self._skills),
                )
        for skill in self._skills:
            if any(trigger.lower() in folded for trigger in skill.triggers):
                return Decision(
                    action="tool",
                    query=probe,
                    tool_name=skill.tool,
                    tool_args={"topic": probe},
                    guidance=skill.body,
                )
        # Explicit 「请记住」 is a write path, not a corpus lookup — otherwise
        # agent-memory primers steal the turn via lexical overlap.
        from knowhow.memory import explicit_remember

        if explicit_remember(question) is not None or explicit_remember(probe) is not None:
            return Decision(action="answer", query=probe)
        # Recalled personal facts beat corpus retrieval so offline answers
        # do not bury memory under an unrelated RAG hit.
        if memories:
            return Decision(action="answer", query=probe)
        hits = self._store.search(probe, k=1)
        if hits and hits[0].score >= self._threshold:
            return Decision(action="retrieve", query=probe)
        return Decision(action="answer", query=probe)


class ModelDecider:
    """Ask the chat model for a JSON decision. Invalid JSON becomes `answer`."""

    def __init__(self, chat: Chat, catalog: ToolCatalog, skills: list[Skill]) -> None:
        self._chat = chat
        self._catalog = catalog
        self._skills = skills

    async def decide(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[str] = (),
    ) -> Decision:
        tools = ", ".join(self._catalog.names()) or "(none)"
        skills = _skill_catalog(self._skills)
        message = await self._chat.ainvoke(
            [
                SystemMessage(content=_ROUTER_SYSTEM.format(tools=tools, skills=skills)),
                HumanMessage(content=_router_user(question, history, memories)),
            ]
        )
        decision = parse_decision(
            message_text(message.content),
            question=question,
            tool_names=set(self._catalog.names()),
        )
        decision.guidance = guidance_for(decision.tool_name, self._skills)
        return decision


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


def _skill_catalog(skills: list[Skill]) -> str:
    if not skills:
        return "(none)"
    return "\n".join(f"- {skill.name}: {skill.description} → {skill.tool}" for skill in skills)


def _router_user(
    question: str,
    history: Sequence[ChatMessage],
    memories: Sequence[str] = (),
) -> str:
    from knowhow.memory import format_memories

    parts: list[str] = []
    memory_block = format_memories(memories)
    if memory_block:
        parts.append(memory_block)
    if history:
        parts.append(f"对话历史：\n{_format_history(history)}")
    parts.append(f"当前问题：{question}" if parts else question)
    return "\n\n".join(parts)


def _followup_probe(question: str, history: Sequence[ChatMessage]) -> str:
    """Expand short follow-ups with the previous user turn for offline routing."""
    if not history or len(question.strip()) >= 24:
        return question
    prior = [item.content for item in history if item.role == "user"]
    if not prior:
        return question
    return f"{prior[-1]} {question}".strip()


def _format_history(history: Sequence[ChatMessage]) -> str:
    lines: list[str] = []
    for item in history:
        label = "用户" if item.role == "user" else "助手"
        lines.append(f"{label}: {item.content}")
    return "\n".join(lines)
