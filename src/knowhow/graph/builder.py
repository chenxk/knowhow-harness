"""Compile the decide → retrieve | act → respond graph."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from knowhow.graph.state import Branch, GraphState
from knowhow.policy import Decider
from knowhow.rag.store import VectorStore
from knowhow.respond import Responder
from knowhow.tools.catalog import ToolCatalog
from knowhow.types import ChatMessage, message_text


def build_graph(
    *,
    decider: Decider,
    store: VectorStore,
    catalog: ToolCatalog,
    responder: Responder,
    top_k: int,
    history_turns: int = 12,
) -> CompiledStateGraph:
    """Compile the runtime graph with an in-memory checkpoint."""

    async def decide(state: GraphState) -> dict[str, object]:
        question = _last_human(state)
        history = _prior_chat(state, limit=history_turns)
        memories = list(state.get("memories") or [])
        decision = await decider.decide(question, history=history, memories=memories)
        return {
            "action": decision.action,
            "query": decision.query or question,
            "tool_name": decision.tool_name,
            "tool_args": decision.tool_args,
            "guidance": decision.guidance,
        }

    async def retrieve(state: GraphState) -> dict[str, object]:
        hits = store.search(state["query"], k=top_k)
        sources: list[str] = []
        for hit in hits:
            if hit.chunk.source not in sources:
                sources.append(hit.chunk.source)
        return {
            "context": [hit.chunk.text for hit in hits],
            "sources": sources,
        }

    async def act(state: GraphState) -> dict[str, object]:
        if not state["tool_name"]:
            raise ValueError("tool branch requires tool_name")
        output = await catalog.ainvoke(state["tool_name"], state["tool_args"])
        return {"tool_output": output}

    async def respond(state: GraphState) -> dict[str, object]:
        parts: list[str] = []
        writer = get_stream_writer()
        history = _prior_chat(state, limit=history_turns)
        memories = list(state.get("memories") or [])
        async for part in responder.astream(
            question=_last_human(state),
            query=state["query"],
            context=state["context"],
            sources=state["sources"],
            tool_output=state["tool_output"],
            guidance=state["guidance"],
            history=history,
            memories=memories,
        ):
            if part.kind == "thinking":
                writer({"thinking": part.text})
                continue
            parts.append(part.text)
            writer({"text": part.text})
        return {"messages": [AIMessage(content="".join(parts))]}

    builder = StateGraph(GraphState)
    builder.add_node("decide", decide)
    builder.add_node("retrieve", retrieve)
    builder.add_node("act", act)
    builder.add_node("respond", respond)
    builder.add_edge(START, "decide")
    builder.add_conditional_edges("decide", _branch, ["retrieve", "act", "respond"])
    builder.add_edge("retrieve", "respond")
    builder.add_edge("act", "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=MemorySaver())


def _branch(state: GraphState) -> Branch:
    if state["action"] == "retrieve":
        return "retrieve"
    if state["action"] == "tool":
        return "act"
    return "respond"


def _last_human(state: GraphState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    raise ValueError("graph state has no human message")


def _prior_chat(state: GraphState, *, limit: int) -> list[ChatMessage]:
    """User/assistant turns before the current question, truncated to `limit`."""
    rows: list[ChatMessage] = []
    for message in state["messages"]:
        if isinstance(message, HumanMessage):
            rows.append(ChatMessage(role="user", content=message_text(message.content)))
        elif isinstance(message, AIMessage):
            rows.append(
                ChatMessage(role="assistant", content=message_text(message.content))
            )
    if rows and rows[-1].role == "user":
        rows = rows[:-1]
    if limit > 0:
        return rows[-limit:]
    return rows
