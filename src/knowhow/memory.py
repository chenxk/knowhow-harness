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
MemoryOp = Literal["add", "update", "delete", "noop"]

_REMEMBER = re.compile(r"请记住[：:]\s*(.+)", re.DOTALL)
_NAME = re.compile(r"我叫\s*([^\s，。！？,.!?；;：:]{1,40})")
_AT = re.compile(r"我在\s*([^\s，。！？,.!?；;：:]{1,40})")
_MOVED = re.compile(r"我(?:搬到|搬去)\s*([^\s，。！？,.!?；;：:]{1,40})")
_LIKE = re.compile(r"我喜欢\s*([^\s，。！？,.!?；;：:]{1,40})")
_FORGET = re.compile(r"忘掉|不要记住|别记了")
_SLOT_NAME = re.compile(r"(?:用户|我)叫")
_SLOT_PLACE = re.compile(r"(?:用户|我)(?:在|搬到|搬去)")
_SLOT_LIKE = re.compile(r"(?:用户|我)喜欢")
_PARTICLE = re.compile(r"[了啦吧呢啊]+$")
_NOT_FACT = re.compile(r"什么|哪|谁|吗|几")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_EPHEMERAL = re.compile(
    r"(帮我|提醒我|查一下|订一张|发邮件|待办|\btodo\b|今天先|明天再|稍后|等会儿|等下)",
    re.IGNORECASE,
)
_OPS = {"add", "update", "delete", "noop"}
_RECALL_BAND = 0.05


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
    last_recalled_at: str | None = None
    active: bool = True


class MemoryHit(BaseModel):
    """A recalled memory with lexical score."""

    item: MemoryItem
    score: float


class ExtractedFact(BaseModel):
    """One maintenance op from offline rules or the live extractor."""

    content: str
    category: MemoryCategory = "other"
    durable: bool = True
    op: MemoryOp = "add"
    target_id: str | None = None


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
              hit_count INTEGER NOT NULL DEFAULT 1,
              last_recalled_at TEXT
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
        if "last_recalled_at" not in cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN last_recalled_at TEXT")

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

    def revise(
        self,
        memory_id: str,
        content: str,
        *,
        category: MemoryCategory | None = None,
        source_session_id: str | None = None,
        force_active: bool = False,
    ) -> MemoryItem | None:
        """Overwrite one row's text. Keep status unless force_active."""
        item = self.get(memory_id)
        cleaned = content.strip()
        if item is None or not item.active or not cleaned:
            return None
        status: MemoryStatus = "active" if force_active else item.status
        category_value = item.category if category is None else category
        source = item.source_session_id if source_session_id is None else source_session_id
        now = _now()
        self._conn.execute(
            """
            UPDATE memories
            SET content = ?, category = ?, source_session_id = ?,
                updated_at = ?, active = 1, status = ?
            WHERE id = ? AND active = 1
            """,
            (cleaned, category_value, source, now, status, memory_id),
        )
        self._conn.commit()
        return self.get(memory_id)

    def mark_recalled(self, memory_ids: Sequence[str]) -> None:
        """Stamp last_recalled_at for rows injected into this turn.

        Recall never deletes active memories that have gone unused.
        """
        if not memory_ids:
            return
        now = _now()
        self._conn.executemany(
            """
            UPDATE memories SET last_recalled_at = ?
            WHERE id = ? AND active = 1
            """,
            [(now, memory_id) for memory_id in memory_ids],
        )
        self._conn.commit()

    def related(
        self,
        query: str,
        *,
        k: int = 8,
        user_id: str = "local",
    ) -> list[MemoryItem]:
        """Pending and active rows for this turn: same-slot facts, then lexical hits."""
        picked: list[MemoryItem] = []
        seen: set[str] = set()
        slot = utterance_slot(query)
        if slot is not None:
            for item in self.list(user_id=user_id, statuses=("pending", "active")):
                if utterance_slot(item.content) == slot and item.id not in seen:
                    picked.append(item)
                    seen.add(item.id)
        for hit in self.search(
            query,
            k=k,
            user_id=user_id,
            statuses=("pending", "active"),
        ):
            if hit.item.id not in seen:
                picked.append(hit.item)
                seen.add(hit.item.id)
        return picked[:k]

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
        ranked.sort(key=_hit_rank, reverse=True)
        return ranked[:k]


def extract_facts_offline(
    turns: Sequence[ChatMessage],
    existing: Sequence[MemoryItem] = (),
    *,
    dedupe_threshold: float = 0.82,
) -> list[ExtractedFact]:
    """Rule-based maintenance: same-slot corrections update, forget phrases delete."""
    found: list[ExtractedFact] = []
    deletes: list[ExtractedFact] = []
    seen: set[str] = set()
    slot_facts: dict[str, ExtractedFact] = {}
    for turn in turns:
        if turn.role != "user":
            continue
        text = turn.content.strip()
        if _FORGET.search(text):
            target = _forget_target(text, existing)
            if target is not None:
                deletes.append(
                    ExtractedFact(
                        content=target.content,
                        category=target.category,
                        durable=True,
                        op="delete",
                        target_id=target.id,
                    )
                )
            continue
        for fact in _rules(text):
            if not fact.durable:
                continue
            slot = utterance_slot(fact.content)
            if slot is None:
                key = fact.content.casefold()
                if key in seen:
                    continue
                seen.add(key)
                found.append(fact)
                continue
            slot_facts[slot] = fact
    for slot, fact in slot_facts.items():
        target = correction_target(
            fact.content,
            existing,
            dedupe_threshold=dedupe_threshold,
            slot=slot,
        )
        if target is None:
            found.append(fact)
            continue
        found.append(fact.model_copy(update={"op": "update", "target_id": target.id}))
    found.extend(deletes)
    return found


def explicit_remember(text: str) -> str | None:
    """Return the payload after 「请记住：」 when present."""
    match = _REMEMBER.search(text.strip())
    if match is None:
        return None
    payload = match.group(1).strip()
    return payload or None


def utterance_slot(text: str) -> str | None:
    """Return name/place/like when text is one of the offline fact templates."""
    if _SLOT_NAME.search(text):
        return "name"
    if _SLOT_PLACE.search(text):
        return "place"
    if _SLOT_LIKE.search(text):
        return "like"
    return None


def memory_similarity(left: str, right: str) -> float:
    """Lexical cosine used for dedupe, slot correction, and forget targeting."""
    return _cosine(_memory_terms(left), _memory_terms(right))


def correction_target(
    content: str,
    existing: Sequence[MemoryItem],
    *,
    dedupe_threshold: float,
    slot: str | None = None,
) -> MemoryItem | None:
    """Same-slot row to overwrite when the new wording is not a near-duplicate.

    Near-duplicates return None so the caller can upsert and keep hit promotion.
    """
    wanted = slot if slot is not None else utterance_slot(content)
    if wanted is None:
        return None
    rows = [item for item in existing if item.active and utterance_slot(item.content) == wanted]
    if not rows:
        return None
    rows.sort(key=lambda item: memory_similarity(content, item.content), reverse=True)
    best = rows[0]
    if memory_similarity(content, best.content) >= dedupe_threshold:
        return None
    return best


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
    if name is not None and _keep_value(name.group(1)):
        rows.append(
            ExtractedFact(
                content=f"用户叫{name.group(1).strip()}",
                category="profile",
                durable=True,
            )
        )
    place = _place_phrase(text)
    if place is not None:
        rows.append(
            ExtractedFact(
                content=f"用户在{place}",
                category="profile",
                durable=True,
            )
        )
    like = _LIKE.search(text)
    if like is not None and _keep_value(like.group(1)):
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
    recalled = row["last_recalled_at"] if "last_recalled_at" in keys else None
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
        last_recalled_at=None if recalled is None else str(recalled),
        active=bool(row["active"]),
    )


def _new_id() -> str:
    return "m" + uuid.uuid4().hex[:15]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _place_phrase(text: str) -> str | None:
    moved = _MOVED.search(text)
    if moved is not None:
        place = _trim_particle(moved.group(1))
        return place if _keep_value(place) else None
    at = _AT.search(text)
    if at is None:
        return None
    place = _trim_particle(at.group(1))
    return place if _keep_value(place) else None


def _keep_value(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    return _NOT_FACT.search(cleaned) is None


def _trim_particle(value: str) -> str:
    return _PARTICLE.sub("", value.strip()).strip()


def _forget_target(text: str, existing: Sequence[MemoryItem]) -> MemoryItem | None:
    best: MemoryItem | None = None
    best_score = 0.0
    for item in existing:
        if not item.active:
            continue
        score = memory_similarity(text, item.content)
        if score > best_score:
            best = item
            best_score = score
    return best


def _hit_rank(hit: MemoryHit) -> tuple[int, str]:
    """Relevance band first; within a close band, recently recalled rows win."""
    band = int(hit.score / _RECALL_BAND)
    recalled = hit.item.last_recalled_at or ""
    return (band, recalled)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[key] * right[key] for key in set(left) & set(right))
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm)


_EXTRACT_SYSTEM = """维护跨会话原子事实。只输出 JSON 数组，不要输出别的文字。
每项字段：
- op：add | update | delete | noop
- id：update 或 delete 时填写已有记忆的 id；add / noop 省略
- content：一句话事实（delete / noop 可省略）
- category：preference | profile | decision | other
- durable：bool

add：没有可合并的旧条，记一条新事实。
update：同一件事有更准的说法，覆盖该 id 的文本。
delete：用户明确说忘掉、不要记住、别记了，或否定某条旧事实。
noop：闲聊、重复、一次性任务。
durable=false：一次性任务或临时上下文，不要记。
也可用 {"action":"ignore"} 跳过该项。
不要存整段聊天。没有要做的维护时输出 []。
"""


async def extract_facts_live(
    chat: object,
    turns: Sequence[ChatMessage],
    existing: Sequence[MemoryItem] = (),
) -> list[ExtractedFact]:
    """Ask the chat model for memory ops. Invalid JSON becomes no writes."""
    from langchain_core.messages import HumanMessage, SystemMessage

    if not turns:
        return []
    payload = [{"role": item.role, "content": item.content} for item in turns]
    lines = [f"- id={item.id} status={item.status} text={item.content}" for item in existing]
    remembered = "已有相关记忆：\n" + ("\n".join(lines) if lines else "（无）")
    ainvoke = getattr(chat, "ainvoke", None)
    if ainvoke is None:
        return []
    message = await ainvoke(
        [
            SystemMessage(content=_EXTRACT_SYSTEM),
            HumanMessage(content=f"{remembered}\n对话：\n{payload}"),
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
        op_raw = str(item.get("op") or item.get("action") or "").strip().casefold()
        if op_raw == "ignore":
            continue
        target_id = str(item.get("id") or "").strip() or None
        if op_raw not in _OPS:
            op_raw = "add"
            target_id = None
        if op_raw == "noop":
            continue
        if op_raw == "update" and target_id is None:
            op_raw = "add"
        content = str(item.get("content") or "").strip()
        category = str(item.get("category") or "other")
        if category not in allowed:
            category = "other"
        if op_raw == "delete":
            if target_id is None and not content:
                continue
            rows.append(
                ExtractedFact(
                    content=content or target_id or "",
                    category=cast(MemoryCategory, category),
                    durable=True,
                    op="delete",
                    target_id=target_id,
                )
            )
            continue
        if not content:
            continue
        durable_raw = item.get("durable", True)
        durable = durable_raw is not False and str(durable_raw).casefold() not in {
            "false",
            "0",
            "no",
        }
        op: MemoryOp = "update" if op_raw == "update" else "add"
        rows.append(
            ExtractedFact(
                content=content,
                category=cast(MemoryCategory, category),
                durable=durable,
                op=op,
                target_id=target_id if op == "update" else None,
            )
        )
    return rows
