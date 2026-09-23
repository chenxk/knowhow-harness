"""Build a turn dissection from real runtime state (not model narration)."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

from knowhow.labs import LabSpec, lab_for_topic
from knowhow.types import Action, RouteReason

_SECRET = re.compile(
    r"(?i)(sk-[a-z0-9]{8,}|bearer\s+\S+|api[_-]?key\s*[:=]\s*\S+|"
    r"openai_api_key\s*[:=]\s*\S+|langfuse[_-]?(?:public|secret)[_-]?key\s*[:=]\s*\S+)"
)
_PREVIEW = 280
_TOOL_SUMMARY = 400


class RouteView(BaseModel):
    """Routing outcome for this turn."""

    action: Action
    tool_name: str = ""
    sources: list[str] = Field(default_factory=list)
    query: str = ""


class WhyView(BaseModel):
    """Human-readable reason the router took this branch."""

    reason: RouteReason = "unknown"
    detail: str = ""


class InjectedView(BaseModel):
    """What was injected into decide/respond before generation."""

    history_turns: int = 0
    memories: list[str] = Field(default_factory=list)
    guidance_present: bool = False


class HistoryLine(BaseModel):
    """One prior turn as the model saw it (truncated)."""

    role: str
    chars: int
    preview: str


class ModelVisibleView(BaseModel):
    """Skeleton of prompt assembly inputs for this turn."""

    system_kind: Literal["answer", "coach"] = "answer"
    guidance_present: bool = False
    guidance_preview: str = ""
    history_turns: int = 0
    history: list[HistoryLine] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    context_previews: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    tool_output_preview: str = ""
    query: str = ""


class UserVisibleView(BaseModel):
    """What the user saw for this turn."""

    question: str = ""
    answer_snippet: str = ""


class TurnDissection(BaseModel):
    """Self-explain payload persisted on assistant messages and SSE done."""

    route: RouteView
    why: WhyView
    injected: InjectedView
    tool_output_summary: str = ""
    trace_id: str | None = None
    tracing: bool = False
    langfuse_hint: str | None = None
    user_visible: UserVisibleView = Field(default_factory=UserVisibleView)
    model_visible: ModelVisibleView = Field(default_factory=ModelVisibleView)
    lab: LabSpec | None = None
    default_open: bool = False


REASON_LABELS: dict[RouteReason, str] = {
    "skill_trigger": "命中 Skill 触发词",
    "tool_name": "问题中出现工具名",
    "model": "模型路由决定",
    "scripted_retrieve": "offline 检索分过阈",
    "scripted_memory": "offline 有召回记忆，直答",
    "scripted_remember": "显式「请记住」写路径",
    "scripted_fallback": "offline 无检索命中，直答",
    "unknown": "原因未记录",
}


def redact_secrets(text: str) -> str:
    """Strip credential-looking spans before showing debug text in the UI."""
    return _SECRET.sub("[REDACTED]", text)


def truncate(text: str, limit: int = _PREVIEW) -> str:
    """Hard-cap UI text; mark truncation explicitly."""
    cleaned = redact_secrets(text.replace("\r\n", "\n").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _langfuse_traces_url(host: str, project_id: str, trace_id: str) -> str | None:
    """Project traces search URL. Missing host or project id yields no link."""
    base = host.strip().rstrip("/")
    project = project_id.strip()
    trace = trace_id.strip()
    if not base or not project or not trace:
        return None
    return f"{base}/project/{quote(project, safe='')}/traces?search={quote(trace, safe='')}"


def build_dissection(
    *,
    question: str,
    answer: str,
    values: dict[str, Any],
    history_limit: int,
    memories: list[str],
    route_reason: RouteReason | str = "unknown",
    trace_id: str | None,
    tracing: bool,
    langfuse_host: str = "",
    langfuse_project_id: str = "",
) -> TurnDissection:
    """Assemble dissection from graph checkpoint values and run metadata."""
    action = _as_action(values.get("action"))
    tool_name = str(values.get("tool_name") or "")
    sources = [item for item in (values.get("sources") or []) if isinstance(item, str)]
    query = str(values.get("query") or question)
    guidance = str(values.get("guidance") or "")
    tool_output = str(values.get("tool_output") or "")
    context = [item for item in (values.get("context") or []) if isinstance(item, str)]
    reason = _as_reason(route_reason or values.get("route_reason"))
    raw_args = values.get("tool_args")
    topic = query
    if isinstance(raw_args, dict):
        topic = str(raw_args.get("topic") or query)
    lab = lab_for_topic(topic) if tool_name == "learn_agent" else None

    history = _history_lines(values, history_limit)
    model_visible = ModelVisibleView(
        system_kind="coach" if guidance.strip() else "answer",
        guidance_present=bool(guidance.strip()),
        guidance_preview=truncate(guidance, 200),
        history_turns=len(history),
        history=history,
        memories=[truncate(item, 160) for item in memories],
        context_previews=[truncate(item, 160) for item in context[:4]],
        sources=sources,
        tool_output_preview=truncate(tool_output, _TOOL_SUMMARY),
        query=truncate(query, 200),
    )
    hint = None
    if tracing and trace_id:
        hint = _langfuse_traces_url(langfuse_host, langfuse_project_id, trace_id)

    return TurnDissection(
        route=RouteView(
            action=action,
            tool_name=tool_name,
            sources=sources,
            query=truncate(query, 200),
        ),
        why=WhyView(reason=reason, detail=REASON_LABELS.get(reason, REASON_LABELS["unknown"])),
        injected=InjectedView(
            history_turns=len(history),
            memories=[truncate(item, 160) for item in memories],
            guidance_present=bool(guidance.strip()),
        ),
        tool_output_summary=truncate(tool_output, _TOOL_SUMMARY),
        trace_id=trace_id,
        tracing=tracing,
        langfuse_hint=hint,
        user_visible=UserVisibleView(
            question=truncate(question, 400),
            answer_snippet=truncate(answer, 400),
        ),
        model_visible=model_visible,
        lab=lab,
        default_open=bool(lab) or (action == "tool" and tool_name == "learn_agent"),
    )


def _history_lines(values: dict[str, Any], limit: int) -> list[HistoryLine]:
    """Summarize turns the model saw before this question.

    The checkpoint already includes this turn's user message and the answer
    just written, so both are dropped before the history cap is applied.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from knowhow.types import message_text

    raw = values.get("messages") or []
    if not isinstance(raw, list):
        return []
    rows: list[HistoryLine] = []
    for message in raw:
        if isinstance(message, HumanMessage):
            role = "user"
            text = message_text(message.content)
        elif isinstance(message, AIMessage):
            role = "assistant"
            text = message_text(message.content)
        else:
            continue
        rows.append(
            HistoryLine(role=role, chars=len(text), preview=truncate(text, 120))
        )
    if rows and rows[-1].role == "assistant":
        rows = rows[:-1]
    if rows and rows[-1].role == "user":
        rows = rows[:-1]
    if limit > 0:
        rows = rows[-limit:]
    return rows


def _as_action(value: object) -> Action:
    if value in ("retrieve", "tool", "answer"):
        return value  # type: ignore[return-value]
    return "answer"


def _as_reason(value: object) -> RouteReason:
    if value in REASON_LABELS:
        return value  # type: ignore[return-value]
    return "unknown"
