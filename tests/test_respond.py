"""Responder thinking / answer fragment streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace

import pytest

from knowhow.config import Settings
from knowhow.graph.builder import build_graph
from knowhow.memory import SqliteMemoryStore
from knowhow.observe.tracing import Tracer
from knowhow.policy import ScriptedDecider
from knowhow.rag.store import InMemoryStore
from knowhow.respond import ModelResponder, OfflineResponder, _delta_reasoning
from knowhow.runtime import Runtime
from knowhow.tools.catalog import StaticToolCatalog
from knowhow.types import AnswerPart, ChatMessage, StreamEvent


@pytest.mark.asyncio
async def test_offline_responder_yields_text_only() -> None:
    parts = [
        part
        async for part in OfflineResponder().astream(
            question="你好",
            query="你好",
            context=[],
            sources=[],
            tool_output="",
            guidance="",
        )
    ]
    assert parts
    assert all(part.kind == "text" for part in parts)
    assert "".join(part.text for part in parts).startswith("没有检索到资料")


@pytest.mark.asyncio
async def test_model_responder_emits_thinking_from_raw_deltas() -> None:
    class _Stream:
        def __init__(self, chunks: list[object]) -> None:
            self._chunks = chunks

        def __aiter__(self) -> AsyncIterator[object]:
            async def _gen() -> AsyncIterator[object]:
                for chunk in self._chunks:
                    yield chunk

            return _gen()

    class _Completions:
        async def create(self, **kwargs: object) -> _Stream:
            assert kwargs["stream"] is True
            return _Stream(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    reasoning_content="先想一下",
                                    content=None,
                                    model_extra={},
                                )
                            )
                        ]
                    ),
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    reasoning_content=None,
                                    content="答案",
                                    model_extra={},
                                )
                            )
                        ]
                    ),
                ]
            )

    chat = SimpleNamespace(
        async_client=SimpleNamespace(create=_Completions().create),
        model_name="fake-reasoner",
        temperature=0,
        astream=None,
    )
    parts = [
        part
        async for part in ModelResponder(chat).astream(  # type: ignore[arg-type]
            question="q",
            query="q",
            context=[],
            sources=[],
            tool_output="",
            guidance="",
        )
    ]
    assert parts == [
        AnswerPart(kind="thinking", text="先想一下"),
        AnswerPart(kind="text", text="答案"),
    ]


def test_delta_reasoning_reads_model_extra() -> None:
    delta = SimpleNamespace(
        reasoning_content=None,
        model_extra={"reasoning_content": "extra 思考"},
    )
    assert _delta_reasoning(delta) == "extra 思考"


class _ThinkingResponder:
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
        del question, query, context, sources, tool_output, guidance, history, memories
        yield AnswerPart(kind="thinking", text="推理片段")
        yield AnswerPart(kind="text", text="最终答案")


@pytest.mark.asyncio
async def test_runtime_stream_emits_thinking_events(tmp_path) -> None:
    store = InMemoryStore()
    catalog = StaticToolCatalog()
    await catalog.setup()
    graph = build_graph(
        decider=ScriptedDecider(store, catalog, [], threshold=1.0),
        store=store,
        catalog=catalog,
        responder=_ThinkingResponder(),
        top_k=2,
        history_turns=4,
    )
    settings = Settings(
        _env_file=None,
        mode="offline",
        memory_path=tmp_path / "memory.sqlite",
    )
    runtime = Runtime(
        settings=settings,
        graph=graph,
        store=store,
        memory=SqliteMemoryStore(settings.memory_file),
        tracer=Tracer(settings),
        catalog=catalog,
        skill_names=[],
        corpus_chunks=0,
    )
    events: list[StreamEvent] = []
    async for event in runtime.stream("随便问问", thread_id="t-think"):
        events.append(event)
    thinking = [event for event in events if event.type == "thinking"]
    deltas = [event for event in events if event.type == "delta"]
    done = next(event for event in events if event.type == "done")
    assert [event.text for event in thinking] == ["推理片段"]
    assert [event.text for event in deltas] == ["最终答案"]
    assert done.answer == "最终答案"
