"""HTTP test bench for one in-process runtime."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from knowhow.evals.runner import LangfuseScoreSink, NullScoreSink, load_golden, run_eval
from knowhow.runtime import Runtime, build_runtime
from knowhow.sessions import (
    JsonSessionStore,
    Session,
    SessionMessage,
    SessionSummary,
    is_session_id,
)
from knowhow.types import Action

_PAGE = Path(__file__).with_name("index.html")
_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ChatIn(BaseModel):
    question: str = Field(max_length=4000)
    session_id: str = Field(pattern=_SESSION.pattern)


class SessionCreateIn(BaseModel):
    title: str = Field(default="新对话", max_length=80)


class SessionPatchIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class MetaOut(BaseModel):
    mode: str
    chat_model: str
    corpus_chunks: int
    tools: list[str]
    skills: list[str]
    tracing: bool


class EvalRowOut(BaseModel):
    case_id: str
    passed: bool
    action: Action
    failures: list[str]


class EvalOut(BaseModel):
    passed: int
    failed: int
    rows: list[EvalRowOut]
    scored: bool = False


class ScoreIn(BaseModel):
    trace_id: str = Field(min_length=8, max_length=128)
    value: float = Field(ge=0, le=1)
    comment: str = Field(default="", max_length=500)


class ScoreOut(BaseModel):
    ok: bool
    name: str
    value: float
    trace_id: str


def create_app(runtime: Runtime | None = None) -> FastAPI:
    """Serve the test bench. A passed-in runtime is reused; otherwise one is built at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = runtime if runtime is not None else await build_runtime()
        app.state.runtime = current
        app.state.sessions = JsonSessionStore(current.settings.sessions_path)
        app.state.lock = asyncio.Lock()
        yield

    app = FastAPI(title="Knowhow", lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE.read_text(encoding="utf-8")

    @app.get("/api/meta", response_model=MetaOut)
    async def meta() -> MetaOut:
        current: Runtime = app.state.runtime
        return MetaOut(
            mode=current.settings.mode,
            chat_model=current.settings.chat_model,
            corpus_chunks=current.corpus_chunks,
            tools=current.catalog.names(),
            skills=current.skill_names,
            tracing=current.tracer.enabled,
        )

    @app.get("/api/sessions", response_model=list[SessionSummary])
    async def list_sessions() -> list[SessionSummary]:
        store: JsonSessionStore = app.state.sessions
        return store.list()

    @app.post("/api/sessions", response_model=Session)
    async def create_session(
        body: SessionCreateIn = Body(default_factory=SessionCreateIn),
    ) -> Session:
        store: JsonSessionStore = app.state.sessions
        return store.create(title=body.title)

    @app.get("/api/sessions/{session_id}", response_model=Session)
    async def get_session(session_id: str) -> Session:
        store: JsonSessionStore = app.state.sessions
        session = store.get(_check_session(session_id))
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session

    @app.patch("/api/sessions/{session_id}", response_model=Session)
    async def patch_session(session_id: str, body: SessionPatchIn) -> Session:
        store: JsonSessionStore = app.state.sessions
        session = store.rename(_check_session(session_id), body.title)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, bool]:
        store: JsonSessionStore = app.state.sessions
        if not store.delete(_check_session(session_id)):
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"ok": True}

    @app.get("/api/sessions/{session_id}/messages", response_model=list[SessionMessage])
    async def session_messages(session_id: str) -> list[SessionMessage]:
        store: JsonSessionStore = app.state.sessions
        session = store.get(_check_session(session_id))
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session.messages

    @app.post("/api/chat")
    async def chat(body: ChatIn) -> StreamingResponse:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="问题不能为空")
        session_id = _check_session(body.session_id)
        current: Runtime = app.state.runtime
        store: JsonSessionStore = app.state.sessions
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        history = store.chat_history(session, limit=current.settings.history_turns)

        async def events():
            async with app.state.lock:
                done_answer = ""
                done_action: Action = "answer"
                done_sources: list[str] = []
                done_tool = ""
                done_trace: str | None = None
                try:
                    async for event in current.stream(
                        question,
                        thread_id=session_id,
                        history=history,
                    ):
                        payload = event.model_dump(mode="json")
                        yield _sse(payload)
                        await asyncio.sleep(0)
                        if event.type == "done":
                            done_answer = event.answer
                            done_action = event.action
                            done_sources = list(event.sources)
                            done_tool = event.tool_name
                            done_trace = event.trace_id
                    if done_answer:
                        store.append_turn(
                            session_id,
                            question=question,
                            answer=done_answer,
                            action=done_action,
                            sources=done_sources,
                            tool_name=done_tool,
                            trace_id=done_trace,
                        )
                        refreshed = store.get(session_id)
                        if refreshed is not None:
                            yield _sse(
                                {
                                    "type": "session",
                                    "id": refreshed.id,
                                    "title": refreshed.title,
                                    "updated_at": refreshed.updated_at,
                                }
                            )
                    current.tracer.flush()
                except RuntimeError as exc:
                    yield _sse({"type": "error", "text": str(exc)})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/eval", response_model=EvalOut)
    async def evaluate() -> EvalOut:
        current: Runtime = app.state.runtime
        cases = load_golden(current.settings.golden_file.read_text(encoding="utf-8"))
        scored = current.tracer.enabled
        sink = LangfuseScoreSink() if scored else NullScoreSink()
        async with app.state.lock:
            report = await run_eval(current, cases, sink)
            current.tracer.flush()
        return EvalOut(
            passed=report.passed,
            failed=report.failed,
            scored=scored,
            rows=[
                EvalRowOut(
                    case_id=row.case_id,
                    passed=row.passed,
                    action=row.action,
                    failures=list(row.failures),
                )
                for row in report.rows
            ],
        )

    @app.post("/api/scores", response_model=ScoreOut)
    async def score(body: ScoreIn) -> ScoreOut:
        current: Runtime = app.state.runtime
        if not current.tracer.enabled:
            raise HTTPException(status_code=400, detail="未启用 Langfuse，无法写 score")
        try:
            current.tracer.score(
                name="user_feedback",
                value=body.value,
                trace_id=body.trace_id.strip(),
                comment=body.comment.strip(),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ScoreOut(
            ok=True,
            name="user_feedback",
            value=body.value,
            trace_id=body.trace_id.strip(),
        )

    return app


def _sse(payload: dict[str, object]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _check_session(session_id: str) -> str:
    if not is_session_id(session_id):
        raise HTTPException(status_code=400, detail="会话 id 只能包含字母、数字、下划线和连字符")
    return session_id
