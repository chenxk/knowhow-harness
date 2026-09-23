"""HTTP surface for the personal agent UI and /api."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from knowhow.dissection import TurnDissection
from knowhow.evals.runner import LangfuseScoreSink, NullScoreSink, load_golden, run_eval
from knowhow.labs import check_lab, lab_by_id
from knowhow.memory import MemoryItem, SqliteMemoryStore
from knowhow.runtime import Runtime, build_runtime
from knowhow.sessions import (
    JsonSessionStore,
    Session,
    SessionMessage,
    SessionSummary,
    is_session_id,
)
from knowhow.tools.catalog import HybridToolCatalog
from knowhow.tools.mcp_config import (
    McpServer,
    apply_mcp_document,
    delete_server,
    load_user_servers,
    set_server_enabled,
    upsert_server,
)
from knowhow.types import Action

_STATIC = Path(__file__).with_name("static")
_MISSING_UI = "前端尚未构建。请运行：pnpm --dir frontend build\n"
_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MEMORY = re.compile(r"^m[A-Za-z0-9]{1,32}$")


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
    memory_count: int = 0


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


class ConsolidateIn(BaseModel):
    session_id: str = Field(pattern=_SESSION.pattern)


class ScoreIn(BaseModel):
    trace_id: str = Field(min_length=8, max_length=128)
    value: float = Field(ge=0, le=1)
    comment: str = Field(default="", max_length=500)


class ScoreOut(BaseModel):
    ok: bool
    name: str
    value: float
    trace_id: str


class McpServerIn(BaseModel):
    name: str = Field(max_length=64)
    enabled: bool = True
    transport: Literal["stdio", "http", "sse"] = "stdio"
    command: str = Field(default="", max_length=500)
    args: list[str] = Field(default_factory=list, max_length=32)
    url: str = Field(default="", max_length=2000)


class McpEnabledIn(BaseModel):
    enabled: bool


class McpDocumentIn(BaseModel):
    document: str = Field(max_length=100_000)


class McpServerOut(BaseModel):
    name: str
    enabled: bool
    transport: Literal["stdio", "http", "sse"]
    command: str
    args: list[str]
    url: str
    has_headers: bool = False
    connected: bool
    tool_count: int
    tools: list[str]
    error: str


class McpListOut(BaseModel):
    servers: list[McpServerOut]
    config_error: str = ""
    config_path: str = ""


def create_app(runtime: Runtime | None = None) -> FastAPI:
    """Serve the built SPA and /api. Reuse a passed-in runtime when given."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = runtime if runtime is not None else await build_runtime()
        app.state.runtime = current
        app.state.sessions = JsonSessionStore(current.settings.sessions_path)
        app.state.lock = asyncio.Lock()
        yield

    app = FastAPI(title="Knowhow", lifespan=lifespan)
    spa = _STATIC / "index.html"

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
            memory_count=current.memory.count_active(),
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

    @app.get("/api/labs/{lab_id}")
    async def get_lab(lab_id: str) -> dict[str, object]:
        """Return a lab spec plus live pass/fail for each step."""
        spec = lab_by_id(lab_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="实验不存在")
        current: Runtime = app.state.runtime
        rows = current.memory.list()
        checks = check_lab(spec, rows)
        return {
            "lab": spec.model_dump(mode="json"),
            "checks": checks,
        }

    @app.get("/api/memories", response_model=list[MemoryItem])
    async def list_memories() -> list[MemoryItem]:
        current: Runtime = app.state.runtime
        return current.memory.list()

    @app.post("/api/memories/{memory_id}/promote", response_model=MemoryItem)
    async def promote_memory(memory_id: str) -> MemoryItem:
        if _MEMORY.fullmatch(memory_id) is None:
            raise HTTPException(status_code=400, detail="记忆 id 无效")
        current: Runtime = app.state.runtime
        store: SqliteMemoryStore = current.memory
        item = store.promote(memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return item

    @app.post("/api/memories/consolidate")
    async def consolidate_memories(body: ConsolidateIn) -> dict[str, object]:
        """Opt-in batch extract. The UI does not call this when switching sessions."""
        current: Runtime = app.state.runtime
        if not current.settings.memory_consolidate_on_switch:
            return {"ok": True, "skipped": True, "written": 0}
        store: JsonSessionStore = app.state.sessions
        session = store.get(_check_session(body.session_id))
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        history = store.chat_history(session, limit=current.settings.history_turns)
        async with app.state.lock:
            written = await current.consolidate_session(
                history,
                session_id=session.id,
            )
        return {"ok": True, "written": written}

    @app.delete("/api/memories/{memory_id}")
    async def delete_memory(memory_id: str) -> dict[str, bool]:
        if _MEMORY.fullmatch(memory_id) is None:
            raise HTTPException(status_code=400, detail="记忆 id 无效")
        current: Runtime = app.state.runtime
        store: SqliteMemoryStore = current.memory
        if not store.soft_delete(memory_id):
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"ok": True}

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
                done_dissection: TurnDissection | None = None
                try:
                    async for event in current.stream(
                        question,
                        thread_id=session_id,
                        history=history,
                        # Await extract after the answer so /api/memories
                        # refresh right after SSE sees the written facts.
                        defer_extract=False,
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
                            raw = event.dissection
                            if isinstance(raw, TurnDissection):
                                done_dissection = raw
                            elif isinstance(raw, dict):
                                done_dissection = TurnDissection.model_validate(raw)
                    if done_answer:
                        store.append_turn(
                            session_id,
                            question=question,
                            answer=done_answer,
                            action=done_action,
                            sources=done_sources,
                            tool_name=done_tool,
                            trace_id=done_trace,
                            dissection=done_dissection,
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

    @app.get("/api/mcp", response_model=McpListOut)
    async def list_mcp() -> McpListOut:
        current: Runtime = app.state.runtime
        return _mcp_list(current)

    @app.post("/api/mcp", response_model=McpListOut)
    async def save_mcp(body: McpServerIn) -> McpListOut:
        current: Runtime = app.state.runtime
        server = McpServer(
            name=body.name.strip(),
            enabled=body.enabled,
            transport=body.transport,
            command=body.command.strip(),
            args=[item.strip() for item in body.args if item.strip()],
            url=body.url.strip(),
        )
        async with app.state.lock:
            try:
                upsert_server(current.settings.mcp_store_path, server)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            await current.reload_mcp()
        return _mcp_list(current)

    @app.post("/api/mcp/import", response_model=McpListOut)
    async def import_mcp(body: McpDocumentIn) -> McpListOut:
        current: Runtime = app.state.runtime
        async with app.state.lock:
            try:
                apply_mcp_document(current.settings.mcp_store_path, body.document)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            await current.reload_mcp()
        return _mcp_list(current)

    @app.delete("/api/mcp/{name}", response_model=McpListOut)
    async def remove_mcp(name: str) -> McpListOut:
        current: Runtime = app.state.runtime
        async with app.state.lock:
            try:
                delete_server(current.settings.mcp_store_path, name)
            except ValueError as exc:
                status = 404 if str(exc) == "服务不存在" else 400
                raise HTTPException(status_code=status, detail=str(exc)) from exc
            await current.reload_mcp()
        return _mcp_list(current)

    @app.post("/api/mcp/{name}/enabled", response_model=McpListOut)
    async def enable_mcp(name: str, body: McpEnabledIn) -> McpListOut:
        current: Runtime = app.state.runtime
        async with app.state.lock:
            try:
                set_server_enabled(current.settings.mcp_store_path, name, body.enabled)
            except ValueError as exc:
                status = 404 if str(exc) == "服务不存在" else 400
                raise HTTPException(status_code=status, detail=str(exc)) from exc
            await current.reload_mcp()
        return _mcp_list(current)

    if spa.is_file():
        assets = _STATIC / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(spa)

        favicon_path = _STATIC / "favicon.svg"
        if favicon_path.is_file():

            @app.get("/favicon.svg")
            def favicon() -> FileResponse:
                return FileResponse(favicon_path)
    else:

        @app.get("/", response_class=PlainTextResponse)
        def index() -> str:
            return _MISSING_UI

    return app


def _sse(payload: dict[str, object]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _check_session(session_id: str) -> str:
    if not is_session_id(session_id):
        raise HTTPException(status_code=400, detail="会话 id 只能包含字母、数字、下划线和连字符")
    return session_id


def _mcp_list(current: Runtime) -> McpListOut:
    servers, error = load_user_servers(current.settings.mcp_store_path)
    status = _mcp_status(current)
    rows: list[McpServerOut] = []
    for server in servers:
        item = status.get(server.name)
        rows.append(
            McpServerOut(
                name=server.name,
                enabled=server.enabled,
                transport=server.transport,
                command=server.command,
                args=list(server.args),
                url=server.url,
                has_headers=bool(server.headers),
                connected=bool(item and item.connected),
                tool_count=item.tool_count if item else 0,
                tools=list(item.tools) if item else [],
                error=item.error if item else "",
            )
        )
    return McpListOut(
        servers=rows,
        config_error=error or current.mcp_config_error,
        config_path=str(current.settings.mcp_store_path),
    )


def _mcp_status(current: Runtime) -> dict[str, object]:
    catalog = current.catalog
    if not isinstance(catalog, HybridToolCatalog):
        return {}
    return {item.name: item for item in catalog.mcp_status()}
