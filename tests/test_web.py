import asyncio

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
    assert body["tracing"] is False


def test_chat_keeps_the_thread(client: TestClient) -> None:
    first = client.post("/api/chat", json={"question": "如何重置密码", "thread_id": "bench"})
    assert first.status_code == 200
    payload = first.json()
    assert payload["action"] == "retrieve"
    assert payload["sources"] == ["password-reset.md"]
    assert "重置密码" in payload["answer"]

    second = client.post("/api/chat", json={"question": "你好", "thread_id": "bench"})
    assert second.status_code == 200
    messages = second.json()["messages"]
    assert [item["content"] for item in messages if item["role"] == "user"] == [
        "如何重置密码",
        "你好",
    ]
    assert second.json()["action"] == "answer"


def test_blank_question_is_rejected(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "   ", "thread_id": "bench"})
    assert response.status_code == 400
    assert response.json()["detail"] == "问题不能为空"


def test_eval_endpoint_passes_golden_set(client: TestClient) -> None:
    body = client.post("/api/eval").json()
    assert body["failed"] == 0
    assert body["passed"] == 3
