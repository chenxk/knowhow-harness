"""Long-term fact memory. Separate from LangGraph checkpoints and the RAG corpus."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from knowhow.rag.store import terms
from knowhow.types import ChatMessage

MemoryCategory = Literal["preference", "profile", "decision", "other"]

_REMEMBER = re.compile(r"请记住[：:]\s*(.+)", re.DOTALL)
_NAME = re.compile(r"我叫\s*([^\s，。！？,.!?；;：:]{1,40})")
_AT = re.compile(r"我在\s*([^\s，。！？,.!?；;：:]{1,40})")
_LIKE = re.compile(r"我喜欢\s*([^\s，。！？,.!?；;：:]{1,40})")


class MemoryItem(BaseModel):
    """One atomic fact recalled across sessions."""

    id: str
    user_id: str = "local"
    content: str
    category: MemoryCategory = "other"
    source_session_id: str | None = None
    created_at: str
    updated_at: str
    active: bool = True


class MemoryHit(BaseModel):
    """A recalled memory with lexical score."""

    item: MemoryItem
    score: float


class SqliteMemoryStore:
    """SQLite-backed fact store with soft delete and lexical Top-K search."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              content TEXT NOT NULL,
              category TEXT NOT NULL,
              source_session_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def list(self, *, user_id: str = "local", include_inactive: bool = False) -> list[MemoryItem]:
        """Return memories newest-first."""
        if include_inactive:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND active = 1
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def get(self, memory_id: str) -> MemoryItem | None:
        """Load one memory by id."""
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        return None if row is None else _row_to_item(row)

    def add(
        self,
        content: str,
        *,
        category: MemoryCategory = "other",
        user_id: str = "local",
        source_session_id: str | None = None,
    ) -> MemoryItem:
        """Insert a new active memory."""
        now = _now()
        item = MemoryItem(
            id=_new_id(),
            user_id=user_id,
            content=content.strip(),
            category=category,
            source_session_id=source_session_id,
            created_at=now,
            updated_at=now,
            active=True,
        )
        self._conn.execute(
            """
            INSERT INTO memories
              (id, user_id, content, category, source_session_id, created_at, updated_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                item.id,
                item.user_id,
                item.content,
                item.category,
                item.source_session_id,
                item.created_at,
                item.updated_at,
            ),
        )
        self._conn.commit()
        return item

    def upsert(
        self,
        content: str,
        *,
        category: MemoryCategory = "other",
        user_id: str = "local",
        source_session_id: str | None = None,
        dedupe_threshold: float = 0.82,
    ) -> MemoryItem:
        """Insert or update a near-duplicate memory for the same topic."""
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("memory content is empty")
        hits = self.search(cleaned, k=1, user_id=user_id)
        if hits and hits[0].score >= dedupe_threshold:
            existing = hits[0].item
            existing.content = cleaned
            existing.category = category
            if source_session_id:
                existing.source_session_id = source_session_id
            existing.updated_at = _now()
            existing.active = True
            self._conn.execute(
                """
                UPDATE memories
                SET content = ?, category = ?, source_session_id = ?,
                    updated_at = ?, active = 1
                WHERE id = ?
                """,
                (
                    existing.content,
                    existing.category,
                    existing.source_session_id,
                    existing.updated_at,
                    existing.id,
                ),
            )
            self._conn.commit()
            return existing
        return self.add(
            cleaned,
            category=category,
            user_id=user_id,
            source_session_id=source_session_id,
        )

    def soft_delete(self, memory_id: str) -> bool:
        """Mark a memory inactive. Return False when missing."""
        cursor = self._conn.execute(
            """
            UPDATE memories SET active = 0, updated_at = ?
            WHERE id = ? AND active = 1
            """,
            (_now(), memory_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def search(
        self,
        query: str,
        *,
        k: int = 4,
        user_id: str = "local",
    ) -> list[MemoryHit]:
        """Lexical Top-K over active memories (same scoring family as RAG)."""
        query_terms = terms(query)
        if not query_terms:
            return []
        ranked: list[MemoryHit] = []
        for item in self.list(user_id=user_id):
            score = _cosine(query_terms, terms(item.content))
            if score > 0:
                ranked.append(MemoryHit(item=item, score=score))
        ranked.sort(key=lambda hit: hit.score, reverse=True)
        return ranked[:k]


def extract_facts_offline(turns: Sequence[ChatMessage]) -> list[tuple[str, MemoryCategory]]:
    """Rule-based fact extraction for offline mode."""
    found: list[tuple[str, MemoryCategory]] = []
    seen: set[str] = set()
    for turn in turns:
        if turn.role != "user":
            continue
        text = turn.content.strip()
        for fact, category in _rules(text):
            key = fact.casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append((fact, category))
    return found


def explicit_remember(text: str) -> str | None:
    """Return the payload after 「请记住：」 when present."""
    match = _REMEMBER.search(text.strip())
    if match is None:
        return None
    payload = match.group(1).strip()
    return payload or None


def _rules(text: str) -> list[tuple[str, MemoryCategory]]:
    rows: list[tuple[str, MemoryCategory]] = []
    remember = explicit_remember(text)
    if remember is not None:
        rows.append((remember, _guess_category(remember)))
        return rows
    name = _NAME.search(text)
    if name is not None:
        rows.append((f"用户叫{name.group(1).strip()}", "profile"))
    at = _AT.search(text)
    if at is not None:
        rows.append((f"用户在{at.group(1).strip()}", "profile"))
    like = _LIKE.search(text)
    if like is not None:
        rows.append((f"用户喜欢{like.group(1).strip()}", "preference"))
    return rows


def _guess_category(text: str) -> MemoryCategory:
    folded = text.casefold()
    if "喜欢" in folded or "偏好" in folded or "prefer" in folded:
        return "preference"
    if "叫" in folded or "名字" in folded or "在" in folded:
        return "profile"
    if "决定" in folded or "选择" in folded:
        return "decision"
    return "other"


def format_memories(contents: Sequence[str]) -> str:
    """Render recalled facts for prompts."""
    if not contents:
        return ""
    lines = [f"- {item}" for item in contents]
    return "相关长期记忆：\n" + "\n".join(lines)


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        user_id=row["user_id"],
        content=row["content"],
        category=row["category"],
        source_session_id=row["source_session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        active=bool(row["active"]),
    )


def _new_id() -> str:
    return "m" + uuid.uuid4().hex[:15]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[key] * right[key] for key in set(left) & set(right))
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm)


_EXTRACT_SYSTEM = """从对话中抽出值得跨会话记住的原子事实。只输出 JSON 数组。
每项字段：content（一句话事实）、category（preference|profile|decision|other）。
不要存整段聊天。没有可记事实时输出 []。
"""


async def extract_facts_live(
    chat: object,
    turns: Sequence[ChatMessage],
) -> list[tuple[str, MemoryCategory]]:
    """Ask the chat model for atomic facts. Invalid JSON becomes empty."""
    from langchain_core.messages import HumanMessage, SystemMessage

    if not turns:
        return []
    payload = [{"role": item.role, "content": item.content} for item in turns]
    ainvoke = getattr(chat, "ainvoke", None)
    if ainvoke is None:
        return []
    message = await ainvoke(
        [
            SystemMessage(content=_EXTRACT_SYSTEM),
            HumanMessage(content=str(payload)),
        ]
    )
    content = getattr(message, "content", "")
    text = content if isinstance(content, str) else str(content)
    return _parse_extract_json(text)


def _parse_extract_json(text: str) -> list[tuple[str, MemoryCategory]]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL)
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    allowed = {"preference", "profile", "decision", "other"}
    rows: list[tuple[str, MemoryCategory]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        category = str(item.get("category") or "other")
        if not content:
            continue
        if category not in allowed:
            category = "other"
        rows.append((content, category))  # type: ignore[arg-type]
    return rows
