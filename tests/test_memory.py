from pathlib import Path

import pytest

from knowhow.config import Settings
from knowhow.memory import (
    SqliteMemoryStore,
    explicit_remember,
    extract_facts_offline,
    is_ephemeral_turn,
)
from knowhow.runtime import build_runtime
from knowhow.types import ChatMessage


def test_explicit_remember_parses_payload() -> None:
    assert explicit_remember("请记住：我叫小明") == "我叫小明"
    assert explicit_remember("随便聊聊") is None


def test_offline_extract_rules() -> None:
    facts = extract_facts_offline(
        [
            ChatMessage(role="user", content="我叫阿花"),
            ChatMessage(role="user", content="我在上海"),
            ChatMessage(role="user", content="我喜欢深色主题"),
        ]
    )
    contents = [item.content for item in facts]
    assert "用户叫阿花" in contents
    assert "用户在上海" in contents
    assert "用户喜欢深色主题" in contents
    assert all(item.durable for item in facts)


def test_ephemeral_turns_are_skipped() -> None:
    assert is_ephemeral_turn("帮我订一张明天去上海的机票")
    facts = extract_facts_offline(
        [ChatMessage(role="user", content="帮我订一张明天去上海的机票")]
    )
    assert facts == []


def test_sqlite_memory_search_and_soft_delete(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "memory.sqlite")
    store.add("用户叫小明", category="profile", status="active")
    store.add("用户喜欢咖啡", category="preference", status="active")
    hits = store.search("我叫什么", k=2)
    assert hits
    assert "小明" in hits[0].item.content
    assert store.soft_delete(hits[0].item.id)
    assert store.search("我叫什么", k=2) == []
    store.close()


def test_pending_not_in_recall_search(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "memory.sqlite")
    store.add("用户叫阿花", category="profile", status="pending")
    assert store.search("我叫什么", k=2) == []
    assert store.list(statuses=("pending",))
    promoted = store.promote(store.list()[0].id)
    assert promoted is not None
    assert promoted.status == "active"
    hits = store.search("我叫什么", k=2)
    assert hits and "阿花" in hits[0].item.content
    store.close()


def test_upsert_promotes_after_hits(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "memory.sqlite")
    first = store.upsert("用户叫阿花", category="profile", promote_hits=2)
    assert first.status == "pending"
    assert first.hit_count == 1
    second = store.upsert("用户叫阿花", category="profile", promote_hits=2)
    assert second.id == first.id
    assert second.status == "active"
    assert second.hit_count == 2
    store.close()


def test_upsert_correction_updates_content(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "memory.sqlite")
    first = store.upsert("用户喜欢红茶", category="preference", force_active=True)
    updated = store.upsert(
        "用户喜欢绿茶",
        category="preference",
        force_active=True,
        dedupe_threshold=0.5,
    )
    assert updated.id == first.id
    assert "绿茶" in updated.content
    assert updated.status == "active"
    store.close()


def test_migrate_legacy_rows_are_active(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE memories (
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
    conn.execute(
        """
        INSERT INTO memories
          (id, user_id, content, category, source_session_id, created_at, updated_at, active)
        VALUES ('mold', 'local', '用户叫旧名', 'profile', NULL, '2020-01-01T00:00:00+00:00',
                '2020-01-01T00:00:00+00:00', 1)
        """
    )
    conn.commit()
    conn.close()
    store = SqliteMemoryStore(path)
    item = store.get("mold")
    assert item is not None
    assert item.status == "active"
    assert store.search("叫什么", k=1)
    store.close()


@pytest.mark.asyncio
async def test_cross_session_memory_recall(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mode="offline",
        sessions_dir=tmp_path / "sessions",
        memory_path=tmp_path / "memory.sqlite",
    )
    runtime = await build_runtime(settings)
    seed = await runtime.run("请记住：我叫小明", thread_id="thread-a")
    assert "记住" in seed.answer
    assert any(
        "小明" in item.content and item.status == "active"
        for item in runtime.memory.list()
    )

    recall = await runtime.run("我叫什么名字", thread_id="thread-b")
    assert recall.action == "answer"
    assert "小明" in recall.answer

    for item in runtime.memory.list():
        runtime.memory.soft_delete(item.id)
    forgotten = await runtime.run("我叫什么名字", thread_id="thread-c")
    assert "小明" not in forgotten.answer
    assert "没有检索到资料" in forgotten.answer


@pytest.mark.asyncio
async def test_auto_extract_stays_pending_until_repeat(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mode="offline",
        memory_path=tmp_path / "memory.sqlite",
        memory_promote_hits=2,
    )
    runtime = await build_runtime(settings)
    await runtime.run("我叫阿花", thread_id="p1")
    pending = [item for item in runtime.memory.list() if "阿花" in item.content]
    assert len(pending) == 1
    assert pending[0].status == "pending"
    miss = await runtime.run("我叫什么名字", thread_id="p2")
    assert "阿花" not in miss.answer

    await runtime.run("我叫阿花", thread_id="p3")
    active = [item for item in runtime.memory.list() if "阿花" in item.content]
    assert len(active) == 1
    assert active[0].status == "active"
    hit = await runtime.run("我叫什么名字", thread_id="p4")
    assert "阿花" in hit.answer


@pytest.mark.asyncio
async def test_memory_upsert_dedupes(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mode="offline",
        memory_path=tmp_path / "memory.sqlite",
    )
    runtime = await build_runtime(settings)
    await runtime.run("请记住：我喜欢红茶", thread_id="u1")
    await runtime.run("请记住：我喜欢红茶", thread_id="u2")
    likes = [item for item in runtime.memory.list() if "红茶" in item.content]
    assert len(likes) == 1
    assert likes[0].status == "active"


@pytest.mark.asyncio
async def test_consolidate_session_extracts_pending(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mode="offline",
        memory_path=tmp_path / "memory.sqlite",
    )
    runtime = await build_runtime(settings)
    turns = [
        ChatMessage(role="user", content="我在杭州"),
        ChatMessage(role="assistant", content="好的"),
    ]
    written = await runtime.consolidate_session(turns, session_id="s-leave")
    assert written >= 1
    rows = [item for item in runtime.memory.list() if "杭州" in item.content]
    assert rows and rows[0].status == "pending"
