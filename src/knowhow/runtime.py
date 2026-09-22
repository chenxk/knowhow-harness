"""Wire settings, retrieval, tools, and the graph into one runnable object."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from knowhow.config import Settings
from knowhow.graph.builder import build_graph
from knowhow.graph.state import GraphState
from knowhow.observe.tracing import Tracer
from knowhow.policy import ModelDecider, ScriptedDecider
from knowhow.rag.ingest import ingest_dir
from knowhow.rag.store import InMemoryStore
from knowhow.respond import ModelResponder, OfflineResponder
from knowhow.skills import load_skills
from knowhow.tools.catalog import McpToolCatalog, StaticToolCatalog, ToolCatalog
from knowhow.types import Action, ChatMessage, RunResult, StreamEvent, message_text


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
        tracer: Tracer,
        catalog: ToolCatalog,
        skill_names: list[str],
        corpus_chunks: int,
    ) -> None:
        self.settings = settings
        self.graph = graph
        self.store = store
        self.tracer = tracer
        self.catalog = catalog
        self.skill_names = skill_names
        self.corpus_chunks = corpus_chunks

    async def run(self, question: str, *, thread_id: str) -> RunResult:
        """Run one question on a checkpoint thread."""
        done: StreamEvent | None = None
        async for event in self.stream(question, thread_id=thread_id):
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
        )

    async def stream(self, question: str, *, thread_id: str) -> AsyncIterator[StreamEvent]:
        """Yield routing status, then answer text as the model produces it."""
        callbacks = self.tracer.callbacks()
        action: Action = "answer"
        sources: list[str] = []
        tool_name = ""
        async for item in self.graph.astream(
            _initial_state(question),
            _run_config(thread_id, callbacks),
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
                text = payload.get("text")
                if isinstance(text, str) and text:
                    yield StreamEvent(type="delta", text=text)
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values if isinstance(snapshot.values, dict) else {}
        yield StreamEvent(
            type="done",
            action=_as_action(values.get("action"), action),
            sources=list(values.get("sources") or sources),
            tool_name=str(values.get("tool_name") or tool_name),
            trace_id=self.tracer.trace_id(callbacks),
            answer=_last_ai(values),
        )

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
    )
    return Runtime(
        settings=resolved,
        graph=graph,
        store=store,
        tracer=Tracer(resolved),
        catalog=catalog,
        skill_names=[skill.name for skill in skills],
        corpus_chunks=corpus_chunks,
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


def _initial_state(question: str) -> GraphState:
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
    }


def _last_ai(state: object) -> str:
    messages = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(messages, list):
        raise RuntimeError("graph finished without an assistant message")
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message_text(message.content)
    raise RuntimeError("graph finished without an assistant message")
