"""HTTP test bench for one in-process runtime."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from knowhow.evals.runner import LangfuseScoreSink, NullScoreSink, load_golden, run_eval
from knowhow.runtime import Runtime, build_runtime
from knowhow.types import Action, ChatMessage

_PAGE = Path(__file__).with_name("index.html")
_THREAD = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ChatIn(BaseModel):
    question: str = Field(max_length=4000)
    thread_id: str = Field(default="web", pattern=_THREAD.pattern)


class MetaOut(BaseModel):
    mode: str
    chat_model: str
    corpus_chunks: int
    tools: list[str]
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


def create_app(runtime: Runtime | None = None) -> FastAPI:
    """Serve the test bench. A passed-in runtime is reused; otherwise one is built at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = runtime if runtime is not None else await build_runtime()
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
            tracing=current.tracer.enabled,
        )

    @app.get("/api/threads/{thread_id}", response_model=list[ChatMessage])
    async def thread(thread_id: str) -> list[ChatMessage]:
        _check_thread(thread_id)
        current: Runtime = app.state.runtime
        async with app.state.lock:
            return await current.transcript(thread_id)

    @app.post("/api/chat")
    async def chat(body: ChatIn) -> StreamingResponse:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="问题不能为空")
        current: Runtime = app.state.runtime

        async def events():
            async with app.state.lock:
                try:
                    async for event in current.stream(question, thread_id=body.thread_id):
                        yield _sse(event.model_dump(mode="json"))
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
        sink = LangfuseScoreSink() if current.tracer.enabled else NullScoreSink()
        async with app.state.lock:
            report = await run_eval(current, cases, sink)
            current.tracer.flush()
        return EvalOut(
            passed=report.passed,
            failed=report.failed,
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

    return app


def _sse(payload: dict[str, object]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _check_thread(thread_id: str) -> None:
    if _THREAD.fullmatch(thread_id) is None:
        raise HTTPException(status_code=400, detail="线程 id 只能包含字母、数字、下划线和连字符")
