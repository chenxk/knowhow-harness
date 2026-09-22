from pathlib import Path

import pytest

from knowhow.config import Settings
from knowhow.memory import (
    SqliteMemoryStore,
    explicit_remember,
    extract_facts_offline,
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
    contents = [item[0] for item in facts]
    assert "用户叫阿花" in contents
    assert "用户在上海" in contents
    assert "用户喜欢深色主题" in contents


def test_sqlite_memory_search_and_soft_delete(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "memory.sqlite")
    store.add("用户叫小明", category="profile")
    store.add("用户喜欢咖啡", category="preference")
    hits = store.search("我叫什么", k=2)
    assert hits
    assert "小明" in hits[0].item.content
    assert store.soft_delete(hits[0].item.id)
    assert store.search("我叫什么", k=2) == []
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
    assert any("小明" in item.content for item in runtime.memory.list())

    recall = await runtime.run("我叫什么名字", thread_id="thread-b")
    assert recall.action == "answer"
    assert "小明" in recall.answer

    for item in runtime.memory.list():
        runtime.memory.soft_delete(item.id)
    forgotten = await runtime.run("我叫什么名字", thread_id="thread-c")
    assert "小明" not in forgotten.answer
    assert "没有检索到资料" in forgotten.answer


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
