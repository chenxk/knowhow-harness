"""Wire settings, retrieval, tools, and the graph into one runnable object."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from knowhow.config import Settings
from knowhow.dissection import build_dissection
from knowhow.graph.builder import build_graph
from knowhow.graph.state import GraphState
from knowhow.memory import (
    ExtractedFact,
    SqliteMemoryStore,
    explicit_remember,
    extract_facts_live,
    extract_facts_offline,
)
from knowhow.observe.tracing import Tracer
from knowhow.policy import ModelDecider, ScriptedDecider
from knowhow.rag.ingest import ingest_dir
from knowhow.rag.store import InMemoryStore
from knowhow.respond import ModelResponder, OfflineResponder
from knowhow.skills import load_skills
from knowhow.tools.catalog import McpToolCatalog, StaticToolCatalog, ToolCatalog
from knowhow.types import Action, ChatMessage, RunResult, StreamEvent, message_text

_LOG = logging.getLogger(__name__)


class _MermaidGraph(Protocol):
    def draw_mermaid(self) -> str:
        """Return a mermaid diagram of the compiled graph."""


class _Snapshot(Protocol):
    @property
    def values(self) -> object:
        """Checkpoint values for one thread."""


class AgentGraph(Protocol):
    """Compiled LangGraph surface this runtime calls."""

    async def ainvoke(self, state: GraphState, config: dict[str, object]) -> GraphState:
        """Run the graph once."""

    def astream(
        self,
        state: GraphState,
        config: dict[str, object],
        *,
        stream_mode: list[str],
    ) -> AsyncIterator[tuple[str, object]]:
        """Stream graph updates and custom answer deltas."""

    async def aget_state(self, config: dict[str, object]) -> _Snapshot:
        """Read the latest checkpoint for a thread."""

    def get_graph(self) -> _MermaidGraph:
        """Return the drawable graph."""


class Runtime:
    """One process-local agent runtime."""

    def __init__(
        self,
        *,
        settings: Settings,
        graph: AgentGraph,
        store: InMemoryStore,
        memory: SqliteMemoryStore,
        tracer: Tracer,
        catalog: ToolCatalog,
        skill_names: list[str],
        corpus_chunks: int,
        chat: object | None = None,
    ) -> None:
        self.settings = settings
        self.graph = graph
        self.store = store
        self.memory = memory
        self.tracer = tracer
        self.catalog = catalog
        self.skill_names = skill_names
        self.corpus_chunks = corpus_chunks
        self._chat = chat
        self._extract_tasks: set[asyncio.Task[None]] = set()

    async def run(self, question: str, *, thread_id: str) -> RunResult:
        """Run one question on a checkpoint thread."""
        done: StreamEvent | None = None
        async for event in self.stream(question, thread_id=thread_id, defer_extract=False):
            if event.type == "done":
                done = event
        if done is None:
            raise RuntimeError("graph finished without an assistant message")
        return RunResult(
            answer=done.answer,
            action=done.action,
            sources=tuple(done.sources),
            tool_name=done.tool_name,
            trace_id=done.trace_id,
            dissection=done.dissection,
        )

    async def stream(
        self,
        question: str,
        *,
        thread_id: str,
        history: list[ChatMessage] | None = None,
        defer_extract: bool = True,
        user_id: str = "local",
    ) -> AsyncIterator[StreamEvent]:
        """Yield routing status, then answer text as the model produces it."""
        callbacks = self.tracer.callbacks()
        action: Action = "answer"
        sources: list[str] = []
        tool_name = ""
        config = _run_config(thread_id, callbacks)
        memories = self.recall(question, user_id=user_id)
        state = await self._start_state(
            question,
            thread_id=thread_id,
            history=history,
            memories=memories,
        )
        async for item in self.graph.astream(
            state,
            config,
            stream_mode=["updates", "custom"],
        ):
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            mode, payload = item
            if mode == "updates" and isinstance(payload, dict):
                status = _status_from_update(payload, action, sources, tool_name)
                if status is None:
                    continue
                action, sources, tool_name = status
                yield StreamEvent(
                    type="status",
                    action=action,
                    sources=sources,
                    tool_name=tool_name,
                )
            elif mode == "custom" and isinstance(payload, dict):
                thinking = payload.get("thinking")
                if isinstance(thinking, str) and thinking:
                    yield StreamEvent(type="thinking", text=thinking)
                text = payload.get("text")
                if isinstance(text, str) and text:
                    yield StreamEvent(type="delta", text=text)
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values if isinstance(snapshot.values, dict) else {}
        answer = _last_ai(values)
        remembered = explicit_remember(question)
        if remembered is not None:
            self._write_explicit(remembered, session_id=thread_id, user_id=user_id)
        prior = history or []
        if self.settings.history_turns > 0:
            prior = prior[-self.settings.history_turns :]
        trace_id = self.tracer.trace_id(callbacks)
        dissection = build_dissection(
            question=question,
            answer=answer,
            values=values,
            history_limit=self.settings.history_turns,
            memories=memories,
            route_reason=str(values.get("route_reason") or "unknown"),
            trace_id=trace_id,
            tracing=self.tracer.enabled,
            langfuse_host=self.settings.langfuse_host if self.tracer.enabled else "",
        )
        yield StreamEvent(
            type="done",
            action=_as_action(values.get("action"), action),
            sources=list(values.get("sources") or sources),
            tool_name=str(values.get("tool_name") or tool_name),
            trace_id=trace_id,
            answer=answer,
            dissection=dissection,
        )
        if remembered is not None:
            return
        turns = [*prior, ChatMessage(role="user", content=question)]
        if answer:
            turns.append(ChatMessage(role="assistant", content=answer))
        if defer_extract:
            self.schedule_extract(turns, session_id=thread_id, user_id=user_id)
        else:
            await self.extract_after_turn(turns, session_id=thread_id, user_id=user_id)

    def recall(self, question: str, *, user_id: str = "local") -> list[str]:
        """Search promoted (active) memories for injection into decide/respond."""
        hits = self.memory.search(
            question,
            k=self.settings.memory_top_k,
            user_id=user_id,
            statuses=("active",),
        )
        return [hit.item.content for hit in hits]

    def schedule_extract(
        self,
        turns: Sequence[ChatMessage],
        *,
        session_id: str | None,
        user_id: str = "local",
    ) -> None:
        """Fire-and-forget extraction so SSE is not blocked."""
        task = asyncio.create_task(
            self._safe_extract(turns, session_id=session_id, user_id=user_id)
        )
        self._extract_tasks.add(task)
        task.add_done_callback(self._extract_tasks.discard)

    async def extract_after_turn(
        self,
        turns: Sequence[ChatMessage],
        *,
        session_id: str | None,
        user_id: str = "local",
        window: int = 4,
    ) -> None:
        """Light extract: durable facts go to pending (or promote on repeat)."""
        recent = list(turns[-window:]) if turns else []
        if not recent:
            return
        last_user = next(
            (item.content for item in reversed(recent) if item.role == "user"),
            "",
        )
        remembered = explicit_remember(last_user)
        if remembered is not None:
            self._write_explicit(remembered, session_id=session_id, user_id=user_id)
            return
        facts = await self._collect_facts(recent)
        self._ingest_candidates(facts, session_id=session_id, user_id=user_id)

    async def consolidate_session(
        self,
        turns: Sequence[ChatMessage],
        *,
        session_id: str | None,
        user_id: str = "local",
    ) -> int:
        """Merge recent session turns once into pending/active (switch hook)."""
        limit = self.settings.history_turns if self.settings.history_turns > 0 else 12
        recent = list(turns[-limit:]) if turns else []
        if not recent:
            return 0
        for turn in recent:
            if turn.role != "user":
                continue
            remembered = explicit_remember(turn.content)
            if remembered is not None:
                self._write_explicit(remembered, session_id=session_id, user_id=user_id)
        facts = await self._collect_facts(recent)
        durable = [fact for fact in facts if fact.durable]
        self._ingest_candidates(durable, session_id=session_id, user_id=user_id)
        return len(durable)

    def _write_explicit(
        self,
        content: str,
        *,
        session_id: str | None,
        user_id: str,
    ) -> None:
        self.memory.upsert(
            content,
            category="other",
            user_id=user_id,
            source_session_id=session_id,
            dedupe_threshold=self.settings.memory_dedupe_threshold,
            force_active=True,
            promote_hits=self.settings.memory_promote_hits,
        )

    def _ingest_candidates(
        self,
        facts: Sequence[ExtractedFact],
        *,
        session_id: str | None,
        user_id: str,
    ) -> None:
        for fact in facts:
            if not fact.durable:
                continue
            self.memory.upsert(
                fact.content,
                category=fact.category,
                user_id=user_id,
                source_session_id=session_id,
                dedupe_threshold=self.settings.memory_dedupe_threshold,
                status="pending",
                promote_hits=self.settings.memory_promote_hits,
            )

    async def _collect_facts(self, turns: Sequence[ChatMessage]) -> list[ExtractedFact]:
        if self.settings.mode == "live" and self._chat is not None:
            return await extract_facts_live(self._chat, turns)
        return extract_facts_offline(turns)

    async def transcript(self, thread_id: str) -> list[ChatMessage]:
        """Return user and assistant messages stored on a checkpoint thread."""
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values
        if not isinstance(values, dict):
            return []
        raw = values.get("messages") or []
        messages: list[ChatMessage] = []
        for message in raw:
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            else:
                continue
            messages.append(ChatMessage(role=role, content=message_text(message.content)))
        return messages

    async def _safe_extract(
        self,
        turns: Sequence[ChatMessage],
        *,
        session_id: str | None,
        user_id: str,
    ) -> None:
        try:
            await self.extract_after_turn(turns, session_id=session_id, user_id=user_id)
        except Exception:
            _LOG.exception("memory extract failed")

    async def _start_state(
        self,
        question: str,
        *,
        thread_id: str,
        history: list[ChatMessage] | None,
        memories: list[str],
    ) -> GraphState:
        """Seed prior turns when the in-memory checkpoint is empty."""
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values if isinstance(snapshot.values, dict) else {}
        existing = values.get("messages") or []
        if existing:
            state = _initial_state(question, memories=memories)
            return state
        prior = history or []
        if self.settings.history_turns > 0:
            prior = prior[-self.settings.history_turns :]
        return _seeded_state(prior, question, memories=memories)


async def build_runtime(settings: Settings | None = None) -> Runtime:
    """Check settings, index the corpus, and compile the graph."""
    resolved = settings or Settings()
    resolved.check()
    store = InMemoryStore()
    corpus_chunks = ingest_dir(store, resolved.corpus_path)
    catalog: ToolCatalog
    if resolved.mcp_enabled:
        catalog = McpToolCatalog(resolved.mcp_path)
    else:
        catalog = StaticToolCatalog()
    await catalog.setup()
    skills = load_skills(resolved.skills_path)
    missing = [skill.tool for skill in skills if skill.tool not in catalog.names()]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"skills reference unknown tools: {joined}")
    chat: ChatOpenAI | None = None
    if resolved.mode == "live":
        chat = ChatOpenAI(
            model=resolved.chat_model,
            api_key=resolved.openai_api_key,
            base_url=resolved.openai_base_url,
            temperature=0,
            streaming=True,
        )
        decider = ModelDecider(chat, catalog, skills)
        responder = ModelResponder(chat)
    else:
        decider = ScriptedDecider(
            store,
            catalog,
            skills,
            threshold=resolved.retrieve_threshold,
        )
        responder = OfflineResponder()
    graph = build_graph(
        decider=decider,
        store=store,
        catalog=catalog,
        responder=responder,
        top_k=resolved.top_k,
        history_turns=resolved.history_turns,
    )
    return Runtime(
        settings=resolved,
        graph=graph,
        store=store,
        memory=SqliteMemoryStore(resolved.memory_file),
        tracer=Tracer(resolved),
        catalog=catalog,
        skill_names=[skill.name for skill in skills],
        corpus_chunks=corpus_chunks,
        chat=chat,
    )


def _run_config(thread_id: str, callbacks: list[object]) -> dict[str, object]:
    return {
        "callbacks": callbacks,
        "configurable": {"thread_id": thread_id},
        "metadata": {"langfuse_session_id": thread_id},
    }


def _status_from_update(
    payload: dict[str, object],
    action: Action,
    sources: list[str],
    tool_name: str,
) -> tuple[Action, list[str], str] | None:
    changed = False
    decide = payload.get("decide")
    if isinstance(decide, dict):
        action = _as_action(decide.get("action"), action)
        tool_name = str(decide.get("tool_name") or "")
        changed = True
    retrieve = payload.get("retrieve")
    if isinstance(retrieve, dict):
        found = retrieve.get("sources")
        if isinstance(found, list):
            sources = [item for item in found if isinstance(item, str)]
        else:
            sources = []
        changed = True
    if not changed:
        return None
    return action, sources, tool_name


def _as_action(value: object, fallback: Action) -> Action:
    if value == "retrieve":
        return "retrieve"
    if value == "tool":
        return "tool"
    if value == "answer":
        return "answer"
    return fallback


def _initial_state(question: str, *, memories: list[str]) -> GraphState:
    return {
        "messages": [HumanMessage(content=question)],
        "action": "answer",
        "query": question,
        "context": [],
        "sources": [],
        "tool_name": "",
        "tool_args": {},
        "tool_output": "",
        "guidance": "",
        "memories": memories,
        "route_reason": "unknown",
    }


def _seeded_state(
    history: list[ChatMessage],
    question: str,
    *,
    memories: list[str],
) -> GraphState:
    messages: list[HumanMessage | AIMessage] = []
    for item in history:
        if item.role == "user":
            messages.append(HumanMessage(content=item.content))
        else:
            messages.append(AIMessage(content=item.content))
    messages.append(HumanMessage(content=question))
    return {
        "messages": messages,
        "action": "answer",
        "query": question,
        "context": [],
        "sources": [],
        "tool_name": "",
        "tool_args": {},
        "tool_output": "",
        "guidance": "",
        "memories": memories,
        "route_reason": "unknown",
    }


def _last_ai(state: object) -> str:
    messages = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(messages, list):
        raise RuntimeError("graph finished without an assistant message")
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message_text(message.content)
    raise RuntimeError("graph finished without an assistant message")
