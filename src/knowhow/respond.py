"""Final answer writers. Offline echoes context; live calls the chat model."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from knowhow.policy import Chat
from knowhow.types import ChatMessage, message_text

_ANSWER_SYSTEM = """用用户的语言回答。资料和工具结果里没有的事实不要编造。
有来源时在末尾列出来源文件名。
需要分点、标题、强调或代码时使用 Markdown，不要输出 HTML。
结合对话历史理解指代和追问。
长期记忆是跨会话的用户事实，回答个人相关问题时优先使用。
"""


class Responder(Protocol):
    """Produce the user-visible answer from retrieval and tool context."""

    def astream(
        self,
        *,
        question: str,
        query: str,
        context: list[str],
        sources: list[str],
        tool_output: str,
        guidance: str,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[str] = (),
    ) -> AsyncIterator[str]:
        """Yield answer text as it is produced."""


class OfflineResponder:
    """Template answer used when `KNOWHOW_MODE=offline`."""

    async def astream(
        self,
        *,
        question: str,
        query: str,
        context: list[str],
        sources: list[str],
        tool_output: str,
        guidance: str,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[str] = (),
    ) -> AsyncIterator[str]:
        del query, guidance, history
        if tool_output:
            text = tool_output
        elif context:
            lines = ["根据资料：", *context]
            if sources:
                lines.append("来源：" + ", ".join(sources))
            text = "\n".join(lines)
        elif memories:
            text = "根据记忆：\n" + "\n".join(memories)
        elif _is_remember_ack(question):
            text = "好的，我已经记住了。"
        else:
            text = "没有检索到资料，也没有调用工具。"
        for start in range(0, len(text), _CHUNK):
            yield text[start : start + _CHUNK]


class ModelResponder:
    """Chat model answer grounded on retrieved text and tool output."""

    def __init__(self, chat: Chat) -> None:
        self._chat = chat

    async def astream(
        self,
        *,
        question: str,
        query: str,
        context: list[str],
        sources: list[str],
        tool_output: str,
        guidance: str,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[str] = (),
    ) -> AsyncIterator[str]:
        payload = {
            "question": question,
            "query": query,
            "context": context,
            "sources": sources,
            "tool_output": tool_output,
            "guidance": guidance,
            "memories": list(memories),
            "history": [
                {"role": item.role, "content": item.content} for item in history
            ],
        }
        async for chunk in self._chat.astream(
            [
                SystemMessage(content=_ANSWER_SYSTEM),
                HumanMessage(content=str(payload)),
            ]
        ):
            delta = message_text(chunk.content)
            if delta:
                yield delta


def _is_remember_ack(question: str) -> bool:
    from knowhow.memory import explicit_remember

    return explicit_remember(question) is not None


_CHUNK = 24
