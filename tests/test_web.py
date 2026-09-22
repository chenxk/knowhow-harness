import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowhow.config import Settings
from knowhow.runtime import build_runtime
from knowhow.sessions import JsonSessionStore, title_from_text
from knowhow.types import ChatMessage
from knowhow.web.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        mode="offline",
        sessions_dir=tmp_path / "sessions",
    )
    runtime = asyncio.run(build_runtime(settings))
    app = create_app(runtime)
    with TestClient(app) as test_client:
        yield test_client


def test_index_is_the_bench(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "工作台" in response.text
    assert "新对话" in response.text


def test_meta_reports_offline_runtime(client: TestClient) -> None:
    body = client.get("/api/meta").json()
    assert body["mode"] == "offline"
    assert body["corpus_chunks"] >= 2
    assert "lookup_note" in body["tools"]
    assert body["skills"] == ["current-time"]
    assert body["tracing"] is False


def test_sessions_crud_and_chat_persist(client: TestClient) -> None:
    created = client.post("/api/sessions", json={}).json()
    session_id = created["id"]
    assert created["title"] == "新对话"
    assert client.get("/api/sessions").json()[0]["id"] == session_id

    first = client.post(
        "/api/chat",
        json={"question": "如何重置密码", "session_id": session_id},
    )
    assert first.status_code == 200
    events = _events(first.text)
    done = next(event for event in events if event["type"] == "done")
    assert done["action"] == "retrieve"
    assert "重置密码" in done["answer"]
    session_event = next(event for event in events if event["type"] == "session")
    assert session_event["title"] == "如何重置密码"

    loaded = client.get(f"/api/sessions/{session_id}").json()
    assert loaded["title"] == "如何重置密码"
    assert [item["role"] for item in loaded["messages"]] == ["user", "assistant"]
    assert loaded["messages"][0]["content"] == "如何重置密码"

    renamed = client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "密码帮助"},
    ).json()
    assert renamed["title"] == "密码帮助"

    deleted = client.delete(f"/api/sessions/{session_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_chat_followup_uses_history_after_cold_seed(
    client: TestClient,
    tmp_path: Path,
) -> None:
    created = client.post("/api/sessions", json={}).json()
    session_id = created["id"]
    store = JsonSessionStore(tmp_path / "sessions")
    store.append_turn(
        session_id,
        question="如何重置密码",
        answer="根据资料：打开设置。",
        action="retrieve",
        sources=["password-reset.md"],
        tool_name="",
        trace_id=None,
    )

    # New runtime / empty MemorySaver: history must come from the session store.
    settings = Settings(
        _env_file=None,
        mode="offline",
        sessions_dir=tmp_path / "sessions",
    )
    runtime = asyncio.run(build_runtime(settings))
    app = create_app(runtime)
    with TestClient(app) as cold:
        follow = cold.post(
            "/api/chat",
            json={"question": "还有吗", "session_id": session_id},
        )
        events = _events(follow.text)
        done = events[-2] if events[-1]["type"] == "session" else events[-1]
        assert done["type"] == "done"
        # Short follow-up expands with prior user turn and still retrieves.
        assert done["action"] == "retrieve"
        body = cold.get(f"/api/sessions/{session_id}").json()
        assert len(body["messages"]) == 4


def test_blank_question_is_rejected(client: TestClient) -> None:
    session_id = client.post("/api/sessions", json={}).json()["id"]
    response = client.post(
        "/api/chat",
        json={"question": "   ", "session_id": session_id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "问题不能为空"


def test_score_requires_tracing(client: TestClient) -> None:
    response = client.post(
        "/api/scores",
        json={"trace_id": "0123456789abcdef", "value": 1, "comment": "thumbs up"},
    )
    assert response.status_code == 400
    assert "Langfuse" in response.json()["detail"]


def test_eval_endpoint_passes_golden_set(client: TestClient) -> None:
    body = client.post("/api/eval").json()
    assert body["failed"] == 0
    assert body["passed"] == 4
    assert body["scored"] is False


def test_title_from_text_truncates() -> None:
    assert title_from_text("短标题") == "短标题"
    long = "x" * 50
    assert title_from_text(long) == ("x" * 39) + "…"
    assert len(title_from_text(long)) == 40


def test_session_store_roundtrip(tmp_path: Path) -> None:
    store = JsonSessionStore(tmp_path)
    session = store.create()
    store.append_turn(
        session.id,
        question="你好",
        answer="没有检索到资料，也没有调用工具。",
        action="answer",
        sources=[],
        tool_name="",
        trace_id=None,
    )
    loaded = store.get(session.id)
    assert loaded is not None
    assert loaded.title == "你好"
    history = store.chat_history(loaded, limit=12)
    assert history == [
        ChatMessage(role="user", content="你好"),
        ChatMessage(role="assistant", content="没有检索到资料，也没有调用工具。"),
    ]


def _events(body: str) -> list[dict[str, object]]:
    events = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events
