"""Durable chat sessions for the web test bench."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from knowhow.dissection import (
    REASON_LABELS,
    InjectedView,
    RouteView,
    TurnDissection,
    UserVisibleView,
    WhyView,
    truncate,
)
from knowhow.types import Action, ChatMessage

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TITLE_LIMIT = 40


class SessionMessage(BaseModel):
    """One persisted turn. Assistant rows may carry routing metadata."""

    role: Literal["user", "assistant"]
    content: str
    action: Action | None = None
    sources: list[str] = Field(default_factory=list)
    tool_name: str = ""
    trace_id: str | None = None
    dissection: TurnDissection | None = None


class SessionSummary(BaseModel):
    """Sidebar row."""

    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class Session(BaseModel):
    """Full session document on disk."""

    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[SessionMessage] = Field(default_factory=list)


def title_from_text(text: str, *, limit: int = _TITLE_LIMIT) -> str:
    """Build a sidebar title from the first user message."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return "新对话"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def is_session_id(value: str) -> bool:
    """Return True when the id matches the public session id pattern."""
    return _SESSION_ID.fullmatch(value) is not None


class JsonSessionStore:
    """One JSON file per session under a configured directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[SessionSummary]:
        """Return sessions newest-first."""
        rows: list[SessionSummary] = []
        for path in self.root.glob("*.json"):
            try:
                session = Session.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            rows.append(
                SessionSummary(
                    id=session.id,
                    title=session.title,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    message_count=len(session.messages),
                )
            )
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows

    def create(self, *, title: str = "新对话") -> Session:
        """Create an empty session and write it immediately."""
        now = _now()
        session = Session(
            id=_new_id(),
            title=title.strip() or "新对话",
            created_at=now,
            updated_at=now,
            messages=[],
        )
        self._write(session)
        return session

    def get(self, session_id: str) -> Session | None:
        """Load one session, or None when missing."""
        path = self._path(session_id)
        if path is None or not path.is_file():
            return None
        try:
            session = Session.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        _backfill_dissection(session)
        return session

    def rename(self, session_id: str, title: str) -> Session | None:
        """Rename a session. Empty titles become 新对话."""
        session = self.get(session_id)
        if session is None:
            return None
        session.title = title.strip() or "新对话"
        session.updated_at = _now()
        self._write(session)
        return session

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Return False when it was already gone."""
        path = self._path(session_id)
        if path is None or not path.is_file():
            return False
        path.unlink()
        return True

    def append_turn(
        self,
        session_id: str,
        *,
        question: str,
        answer: str,
        action: Action,
        sources: list[str],
        tool_name: str,
        trace_id: str | None,
        dissection: TurnDissection | None = None,
    ) -> Session | None:
        """Append a user/assistant pair and auto-title on the first user turn."""
        session = self.get(session_id)
        if session is None:
            return None
        if not session.messages or session.title in {"", "新对话"}:
            session.title = title_from_text(question)
        session.messages.append(SessionMessage(role="user", content=question))
        session.messages.append(
            SessionMessage(
                role="assistant",
                content=answer,
                action=action,
                sources=list(sources),
                tool_name=tool_name,
                trace_id=trace_id,
                dissection=dissection,
            )
        )
        session.updated_at = _now()
        self._write(session)
        return session

    def chat_history(self, session: Session, *, limit: int) -> list[ChatMessage]:
        """Return recent user/assistant text for model context."""
        rows: list[ChatMessage] = []
        for message in session.messages:
            if message.role not in ("user", "assistant"):
                continue
            rows.append(ChatMessage(role=message.role, content=message.content))
        if limit > 0:
            return rows[-limit:]
        return rows

    def _write(self, session: Session) -> None:
        path = self._path(session.id)
        if path is None:
            raise ValueError(f"invalid session id: {session.id}")
        path.write_text(
            session.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    def _path(self, session_id: str) -> Path | None:
        if not is_session_id(session_id):
            return None
        return self.root / f"{session_id}.json"


def _backfill_dissection(session: Session) -> None:
    """Attach a minimal dissection to assistant rows that were stored without one."""
    question = ""
    for message in session.messages:
        if message.role == "user":
            question = message.content
            continue
        if message.role != "assistant" or message.dissection is not None:
            continue
        action: Action = message.action or "answer"
        message.dissection = TurnDissection(
            route=RouteView(
                action=action,
                tool_name=message.tool_name,
                sources=list(message.sources),
            ),
            why=WhyView(reason="unknown", detail=REASON_LABELS["unknown"]),
            injected=InjectedView(),
            trace_id=message.trace_id,
            user_visible=UserVisibleView(
                question=truncate(question, 400),
                answer_snippet=truncate(message.content, 400),
            ),
        )


def _new_id() -> str:
    return "s" + uuid.uuid4().hex[:15]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
