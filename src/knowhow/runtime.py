"""Wire settings, retrieval, tools, and the graph into one runnable object."""

from __future__ import annotations

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
from knowhow.tools.catalog import McpToolCatalog, StaticToolCatalog, ToolCatalog
from knowhow.types import ChatMessage, RunResult, message_text


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
        corpus_chunks: int,
    ) -> None:
        self.settings = settings
        self.graph = graph
        self.store = store
        self.tracer = tracer
        self.catalog = catalog
        self.corpus_chunks = corpus_chunks

    async def run(self, question: str, *, thread_id: str) -> RunResult:
        """Run one question on a checkpoint thread."""
        callbacks = self.tracer.callbacks()
        result = await self.graph.ainvoke(
            _initial_state(question),
            {
                "callbacks": callbacks,
                "configurable": {"thread_id": thread_id},
                "metadata": {"langfuse_session_id": thread_id},
            },
        )
        return RunResult(
            answer=_last_ai(result),
            action=result["action"],
            sources=tuple(result["sources"]),
            tool_name=result["tool_name"],
            trace_id=self.tracer.trace_id(callbacks),
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
    if resolved.mode == "live":
        chat = ChatOpenAI(
            model=resolved.chat_model,
            api_key=resolved.openai_api_key,
            base_url=resolved.openai_base_url,
            temperature=0,
        )
        decider = ModelDecider(chat, catalog)
        responder = ModelResponder(chat)
    else:
        decider = ScriptedDecider(store, catalog, threshold=resolved.retrieve_threshold)
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
        corpus_chunks=corpus_chunks,
    )


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
    }


def _last_ai(state: GraphState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage):
            return message_text(message.content)
    raise RuntimeError("graph finished without an assistant message")
