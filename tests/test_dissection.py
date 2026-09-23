"""Dissection payload shape, secret redaction, and lab checks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowhow.config import Settings
from knowhow.dissection import build_dissection, redact_secrets
from knowhow.labs import check_lab, lab_by_id, lab_for_topic
from knowhow.memory import MemoryItem
from knowhow.runtime import build_runtime
from knowhow.web.app import create_app


def test_redact_secrets_strips_credentials() -> None:
    text = "prefix sk-abcdefghij123 api_key=supersecretvalue suffix"
    cleaned = redact_secrets(text)
    assert "sk-abcdefghij123" not in cleaned
    assert "supersecretvalue" not in cleaned
    assert "[REDACTED]" in cleaned


def test_build_dissection_redacts_tool_output() -> None:
    view = build_dissection(
        question="lookup_note 密钥",
        answer="done",
        values={
            "action": "tool",
            "tool_name": "lookup_note",
            "tool_output": "see sk-abcdefghij123 and api_key=supersecretvalue",
            "sources": [],
            "query": "密钥",
            "guidance": "",
            "context": [],
            "messages": [],
            "route_reason": "tool_name",
        },
        history_limit=12,
        memories=[],
        route_reason="tool_name",
        trace_id=None,
        tracing=False,
    )
    dumped = view.model_dump_json()
    assert "supersecretvalue" not in dumped
    assert "sk-abcdefghij123" not in dumped
    assert view.route.action == "tool"
    assert view.why.reason == "tool_name"
    assert view.model_visible.system_kind == "answer"
    assert view.user_visible.question == "lookup_note 密钥"


def test_memory_lab_predicates() -> None:
    lab = lab_by_id("memory_promote")
    assert lab is not None
    rows = [
        MemoryItem(
            id="m1",
            content="我喜欢喝绿茶",
            status="active",
            created_at="t",
            updated_at="t",
            active=True,
        ),
        MemoryItem(
            id="m2",
            content="我叫阿花",
            status="pending",
            created_at="t",
            updated_at="t",
            active=False,
        ),
    ]
    checks = check_lab(lab, rows)
    assert checks == {
        "explicit_active": True,
        "implicit_pending": True,
        "promote_active": False,
    }
    assert lab_for_topic("教我工具与 skills") is None
    assert lab_for_topic("教我长期记忆怎么工作") is not None
    assert lab_by_id("missing") is None


@pytest.mark.asyncio
async def test_learn_turn_dissection_shape(tmp_path: Path) -> None:
    runtime = await build_runtime(
        Settings(
            _env_file=None,
            mode="offline",
            memory_path=tmp_path / "memory.sqlite",
        )
    )
    result = await runtime.run("教我长期记忆怎么工作", thread_id="learn")
    view = result.dissection
    assert view is not None
    payload = view.model_dump(mode="json")
    assert payload["route"]["action"] == "tool"
    assert payload["route"]["tool_name"] == "learn_agent"
    assert payload["why"]["reason"] == "skill_trigger"
    assert payload["why"]["detail"]
    assert payload["injected"]["guidance_present"] is True
    assert payload["injected"]["history_turns"] == 0
    assert payload["tool_output_summary"]
    assert payload["model_visible"]["system_kind"] == "coach"
    assert payload["model_visible"]["guidance_present"] is True
    assert payload["user_visible"]["question"].startswith("教我")
    assert payload["user_visible"]["answer_snippet"]
    assert payload["lab"]["id"] == "memory_promote"
    assert len(payload["lab"]["steps"]) == 3
    assert payload["default_open"] is True
    assert payload["tracing"] is False
    assert payload["langfuse_hint"] is None
    assert payload["trace_id"] is None


def test_chat_persists_dissection_and_lab_api(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mode="offline",
        sessions_dir=tmp_path / "sessions",
        memory_path=tmp_path / "memory.sqlite",
    )
    runtime = asyncio.run(build_runtime(settings))
    app = create_app(runtime)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        learn = client.post(
            "/api/chat",
            json={"question": "教我长期记忆怎么工作", "session_id": session_id},
        )
        events = _events(learn.text)
        done = next(event for event in events if event["type"] == "done")
        dissection = done["dissection"]
        assert isinstance(dissection, dict)
        assert dissection["route"]["action"] == "tool"
        assert dissection["why"]["reason"] == "skill_trigger"
        assert dissection["model_visible"]["system_kind"] == "coach"
        assert dissection["user_visible"]["answer_snippet"]

        loaded = client.get(f"/api/sessions/{session_id}").json()
        saved = loaded["messages"][1]["dissection"]
        assert saved["route"]["tool_name"] == "learn_agent"
        assert saved["lab"]["id"] == "memory_promote"

        missing = client.get("/api/labs/not-a-lab")
        assert missing.status_code == 404

        before = client.get("/api/labs/memory_promote").json()
        assert before["lab"]["id"] == "memory_promote"
        assert before["checks"]["explicit_active"] is False

        client.post(
            "/api/chat",
            json={"question": "请记住：我喜欢喝绿茶", "session_id": session_id},
        )
        after = client.get("/api/labs/memory_promote").json()
        assert after["checks"]["explicit_active"] is True
        assert after["checks"]["promote_active"] is False
        again = client.get(f"/api/sessions/{session_id}").json()
        remembered = again["messages"][3]["dissection"]
        assert remembered["injected"]["history_turns"] == 2
        assert remembered["model_visible"]["history"][0]["role"] == "user"
        assert remembered["user_visible"]["question"].startswith("请记住")


def _events(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events
