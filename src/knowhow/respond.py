"""Final answer writers. Offline echoes context; live calls the chat model."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from knowhow.policy import Chat
from knowhow.types import AnswerPart, ChatMessage, message_text

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
    ) -> AsyncIterator[AnswerPart]:
        """Yield thinking and answer fragments as they are produced."""


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
    ) -> AsyncIterator[AnswerPart]:
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
            yield AnswerPart(kind="text", text=text[start : start + _CHUNK])


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
    ) -> AsyncIterator[AnswerPart]:
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
        messages = [
            SystemMessage(content=_ANSWER_SYSTEM),
            HumanMessage(content=str(payload)),
        ]
        async for part in _stream_chat(self._chat, messages):
            yield part


def _is_remember_ack(question: str) -> bool:
    from knowhow.memory import explicit_remember

    return explicit_remember(question) is not None


async def _stream_chat(
    chat: Chat,
    messages: list[SystemMessage | HumanMessage],
) -> AsyncIterator[AnswerPart]:
    """Prefer raw OpenAI deltas so provider `reasoning_content` is not dropped."""
    client = getattr(chat, "async_client", None)
    model = getattr(chat, "model_name", None) or getattr(chat, "model", None)
    if client is not None and isinstance(model, str) and model and hasattr(client, "create"):
        wire = [
            {"role": "system", "content": messages[0].content},
            {"role": "user", "content": messages[1].content},
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": wire,
            "stream": True,
        }
        temperature = getattr(chat, "temperature", None)
        if temperature is not None:
            kwargs["temperature"] = temperature
        # ChatOpenAI.async_client is already openai AsyncCompletions.
        stream = await client.create(**kwargs)
        async for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            thinking = _delta_reasoning(delta)
            if thinking:
                yield AnswerPart(kind="thinking", text=thinking)
            content = getattr(delta, "content", None)
            if isinstance(content, str) and content:
                yield AnswerPart(kind="text", text=content)
        return

    async for chunk in chat.astream(messages):
        thinking = _chunk_reasoning(chunk)
        if thinking:
            yield AnswerPart(kind="thinking", text=thinking)
        delta = message_text(chunk.content)
        if delta:
            yield AnswerPart(kind="text", text=delta)


def _delta_reasoning(delta: object) -> str:
    value = getattr(delta, "reasoning_content", None)
    if isinstance(value, str) and value:
        return value
    extra = getattr(delta, "model_extra", None)
    if isinstance(extra, dict):
        nested = extra.get("reasoning_content")
        if isinstance(nested, str) and nested:
            return nested
    return ""


def _chunk_reasoning(chunk: object) -> str:
    kwargs = getattr(chunk, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return ""
    value = kwargs.get("reasoning_content")
    return value if isinstance(value, str) else ""


_CHUNK = 24
