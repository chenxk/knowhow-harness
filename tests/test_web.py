import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from knowhow.config import Settings
from knowhow.runtime import build_runtime
from knowhow.web.app import create_app


@pytest.fixture
def client():
    runtime = asyncio.run(build_runtime(Settings(_env_file=None, mode="offline")))
    app = create_app(runtime)
    with TestClient(app) as test_client:
        yield test_client


def test_index_is_the_bench(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "测试台" in response.text


def test_meta_reports_offline_runtime(client: TestClient) -> None:
    body = client.get("/api/meta").json()
    assert body["mode"] == "offline"
    assert body["corpus_chunks"] >= 2
    assert "lookup_note" in body["tools"]
    assert body["skills"] == ["current-time"]
    assert body["tracing"] is False


def test_chat_streams_and_keeps_the_thread(client: TestClient) -> None:
    first = client.post("/api/chat", json={"question": "如何重置密码", "thread_id": "bench"})
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    events = _events(first.text)
    deltas = [event["text"] for event in events if event["type"] == "delta"]
    done = events[-1]
    assert len(deltas) >= 2
    assert "".join(deltas) == done["answer"]
    assert done["type"] == "done"
    assert done["action"] == "retrieve"
    assert done["sources"] == ["password-reset.md"]
    assert "重置密码" in done["answer"]

    second = client.post("/api/chat", json={"question": "你好", "thread_id": "bench"})
    assert _events(second.text)[-1]["action"] == "answer"
    history = client.get("/api/threads/bench").json()
    assert [item["content"] for item in history if item["role"] == "user"] == [
        "如何重置密码",
        "你好",
    ]


def _events(body: str) -> list[dict[str, object]]:
    events = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


def test_blank_question_is_rejected(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "   ", "thread_id": "bench"})
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
