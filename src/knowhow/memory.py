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
from typing import Literal, cast

from pydantic import BaseModel

from knowhow.rag.store import terms
from knowhow.types import ChatMessage

MemoryCategory = Literal["preference", "profile", "decision", "other"]
MemoryStatus = Literal["pending", "active"]

_REMEMBER = re.compile(r"请记住[：:]\s*(.+)", re.DOTALL)
_NAME = re.compile(r"我叫\s*([^\s，。！？,.!?；;：:]{1,40})")
_AT = re.compile(r"我在\s*([^\s，。！？,.!?；;：:]{1,40})")
_LIKE = re.compile(r"我喜欢\s*([^\s，。！？,.!?；;：:]{1,40})")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_EPHEMERAL = re.compile(
    r"(帮我|提醒我|查一下|订一张|发邮件|待办|\btodo\b|今天先|明天再|稍后|等会儿|等下)",
    re.IGNORECASE,
)


def _memory_terms(text: str) -> Counter[str]:
    """Lexical bag with CJK unigrams so short personal queries still match."""
    bag = terms(text)
    bag.update(_CJK.findall(text))
    return bag


class MemoryItem(BaseModel):
    """One atomic fact recalled across sessions."""

    id: str
    user_id: str = "local"
    content: str
    category: MemoryCategory = "other"
    status: MemoryStatus = "active"
    hit_count: int = 1
    source_session_id: str | None = None
    created_at: str
    updated_at: str
    active: bool = True


class MemoryHit(BaseModel):
    """A recalled memory with lexical score."""

    item: MemoryItem
    score: float


class ExtractedFact(BaseModel):
    """One candidate fact from offline rules or the live extractor."""

    content: str
    category: MemoryCategory = "other"
    durable: bool = True


class SqliteMemoryStore:
    """SQLite-backed fact store with pending→active promotion and soft delete."""

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
              active INTEGER NOT NULL DEFAULT 1,
              status TEXT NOT NULL DEFAULT 'active',
              hit_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(memories)")}
        if "status" not in cols:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
            )
        if "hit_count" not in cols:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN hit_count INTEGER NOT NULL DEFAULT 1"
            )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def list(
        self,
        *,
        user_id: str = "local",
        include_inactive: bool = False,
        statuses: Sequence[MemoryStatus] | None = None,
    ) -> list[MemoryItem]:
        """Return memories newest-first. Default: non-deleted pending+active."""
        wanted = list(statuses) if statuses is not None else ["pending", "active"]
        placeholders = ",".join("?" for _ in wanted)
        if include_inactive:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memories
                WHERE user_id = ? AND status IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                (user_id, *wanted),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""
                SELECT * FROM memories
                WHERE user_id = ? AND active = 1 AND status IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                (user_id, *wanted),
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def count_active(self, *, user_id: str = "local") -> int:
        """Count promoted (active-status) memories for meta badges."""
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM memories
            WHERE user_id = ? AND active = 1 AND status = 'active'
            """,
            (user_id,),
        ).fetchone()
        return int(row["n"]) if row is not None else 0

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
        status: MemoryStatus = "pending",
        hit_count: int = 1,
    ) -> MemoryItem:
        """Insert a new memory (default pending until promoted)."""
        now = _now()
        item = MemoryItem(
            id=_new_id(),
            user_id=user_id,
            content=content.strip(),
            category=category,
            status=status,
            hit_count=hit_count,
            source_session_id=source_session_id,
            created_at=now,
            updated_at=now,
            active=True,
        )
        self._conn.execute(
            """
            INSERT INTO memories
              (id, user_id, content, category, source_session_id,
               created_at, updated_at, active, status, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                item.id,
                item.user_id,
                item.content,
                item.category,
                item.source_session_id,
                item.created_at,
                item.updated_at,
                item.status,
                item.hit_count,
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
        status: MemoryStatus = "pending",
        promote_hits: int = 2,
        force_active: bool = False,
    ) -> MemoryItem:
        """Insert or update a near-duplicate; promote when forced or hit threshold."""
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("memory content is empty")
        hits = self.search(
            cleaned,
            k=1,
            user_id=user_id,
            statuses=("pending", "active"),
        )
        if hits and hits[0].score >= dedupe_threshold:
            existing = hits[0].item
            existing.content = cleaned
            existing.category = category
            if source_session_id:
                existing.source_session_id = source_session_id
            existing.updated_at = _now()
            existing.active = True
            if force_active or status == "active":
                existing.status = "active"
            else:
                existing.hit_count = max(1, existing.hit_count) + 1
                if existing.hit_count >= promote_hits:
                    existing.status = "active"
            self._conn.execute(
                """
                UPDATE memories
                SET content = ?, category = ?, source_session_id = ?,
                    updated_at = ?, active = 1, status = ?, hit_count = ?
                WHERE id = ?
                """,
                (
                    existing.content,
                    existing.category,
                    existing.source_session_id,
                    existing.updated_at,
                    existing.status,
                    existing.hit_count,
                    existing.id,
                ),
            )
            self._conn.commit()
            return existing
        initial: MemoryStatus = "active" if force_active or status == "active" else "pending"
        return self.add(
            cleaned,
            category=category,
            user_id=user_id,
            source_session_id=source_session_id,
            status=initial,
            hit_count=1,
        )

    def promote(self, memory_id: str) -> MemoryItem | None:
        """Confirm a pending memory into active recall. Return None when missing."""
        item = self.get(memory_id)
        if item is None or not item.active:
            return None
        if item.status == "active":
            return item
        now = _now()
        hit_count = max(1, item.hit_count)
        self._conn.execute(
            """
            UPDATE memories
            SET status = 'active', updated_at = ?, hit_count = ?
            WHERE id = ? AND active = 1
            """,
            (now, hit_count, memory_id),
        )
        self._conn.commit()
        return self.get(memory_id)

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
        statuses: Sequence[MemoryStatus] = ("active",),
    ) -> list[MemoryHit]:
        """Lexical Top-K. Chat recall defaults to promoted (active) only."""
        query_terms = _memory_terms(query)
        if not query_terms:
            return []
        ranked: list[MemoryHit] = []
        for item in self.list(user_id=user_id, statuses=statuses):
            score = _cosine(query_terms, _memory_terms(item.content))
            if score > 0:
                ranked.append(MemoryHit(item=item, score=score))
        ranked.sort(key=lambda hit: hit.score, reverse=True)
        return ranked[:k]


def extract_facts_offline(turns: Sequence[ChatMessage]) -> list[ExtractedFact]:
    """Rule-based fact extraction for offline mode."""
    found: list[ExtractedFact] = []
    seen: set[str] = set()
    for turn in turns:
        if turn.role != "user":
            continue
        text = turn.content.strip()
        for fact in _rules(text):
            if not fact.durable:
                continue
            key = fact.content.casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append(fact)
    return found


def explicit_remember(text: str) -> str | None:
    """Return the payload after 「请记住：」 when present."""
    match = _REMEMBER.search(text.strip())
    if match is None:
        return None
    payload = match.group(1).strip()
    return payload or None


def is_ephemeral_turn(text: str) -> bool:
    """True for one-off tasks / short-lived context (skip auto-extract)."""
    if explicit_remember(text) is not None:
        return False
    return _EPHEMERAL.search(text.strip()) is not None


def _rules(text: str) -> list[ExtractedFact]:
    rows: list[ExtractedFact] = []
    remember = explicit_remember(text)
    if remember is not None:
        rows.append(
            ExtractedFact(
                content=remember,
                category=_guess_category(remember),
                durable=True,
            )
        )
        return rows
    if is_ephemeral_turn(text):
        return rows
    name = _NAME.search(text)
    if name is not None:
        rows.append(
            ExtractedFact(
                content=f"用户叫{name.group(1).strip()}",
                category="profile",
                durable=True,
            )
        )
    at = _AT.search(text)
    if at is not None:
        rows.append(
            ExtractedFact(
                content=f"用户在{at.group(1).strip()}",
                category="profile",
                durable=True,
            )
        )
    like = _LIKE.search(text)
    if like is not None:
        rows.append(
            ExtractedFact(
                content=f"用户喜欢{like.group(1).strip()}",
                category="preference",
                durable=True,
            )
        )
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
    keys = set(row.keys())
    status_raw = row["status"] if "status" in keys else "active"
    status: MemoryStatus = "pending" if status_raw == "pending" else "active"
    hit = int(row["hit_count"]) if "hit_count" in keys else 1
    return MemoryItem(
        id=row["id"],
        user_id=row["user_id"],
        content=row["content"],
        category=row["category"],
        status=status,
        hit_count=hit,
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
每项字段：content（一句话事实）、category（preference|profile|decision|other）、durable（bool）。
durable=true：身份、偏好、长期决定等跨会话仍有用的事实。
durable=false：一次性任务、临时日程、短暂上下文——不要记。
也可用 {"action":"ignore"} 跳过该项。
不要存整段聊天。没有可记事实时输出 []。
"""


async def extract_facts_live(
    chat: object,
    turns: Sequence[ChatMessage],
) -> list[ExtractedFact]:
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


def _parse_extract_json(text: str) -> list[ExtractedFact]:
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
    allowed: set[str] = {"preference", "profile", "decision", "other"}
    rows: list[ExtractedFact] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if str(item.get("action") or "").casefold() == "ignore":
            continue
        content = str(item.get("content") or "").strip()
        category = str(item.get("category") or "other")
        if not content:
            continue
        if category not in allowed:
            category = "other"
        durable_raw = item.get("durable", True)
        durable = durable_raw is not False and str(durable_raw).casefold() not in {
            "false",
            "0",
            "no",
        }
        rows.append(
            ExtractedFact(
                content=content,
                category=cast(MemoryCategory, category),
                durable=durable,
            )
        )
    return rows
