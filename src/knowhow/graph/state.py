"""LangGraph state. Nodes return partial updates; the checkpointer merges them."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from knowhow.types import Action, RouteReason


class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    action: Action
    query: str
    context: list[str]
    sources: list[str]
    tool_name: str
    tool_args: dict[str, str]
    tool_output: str
    guidance: str
    memories: list[str]
    route_reason: RouteReason


Branch = Literal["retrieve", "act", "respond"]
