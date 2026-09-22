"""Command line: run, ingest, eval, graph."""

from __future__ import annotations

import argparse
import asyncio
import sys

from knowhow.config import Settings
from knowhow.evals.runner import LangfuseScoreSink, NullScoreSink, load_golden, run_eval
from knowhow.rag.ingest import ingest_dir
from knowhow.rag.store import InMemoryStore
from knowhow.runtime import build_runtime


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and run one subcommand."""
    parser = argparse.ArgumentParser(prog="knowhow", description="Knowhow agent runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="回答一个问题")
    run_parser.add_argument("question")
    run_parser.add_argument("--thread-id", default="cli")

    sub.add_parser("ingest", help="把 data/corpus 编进内存索引并打印块数")
    sub.add_parser("eval", help="跑 evals/golden.yaml")
    sub.add_parser("graph", help="打印 LangGraph mermaid")

    serve_parser = sub.add_parser("serve", help="启动测试台")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)
    if args.command == "serve":
        _serve(args.host, args.port)
        return
    try:
        asyncio.run(_dispatch(args))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


async def _dispatch(args: argparse.Namespace) -> None:
    settings = Settings()
    if args.command == "ingest":
        settings.check()
        store = InMemoryStore()
        count = ingest_dir(store, settings.corpus_path)
        print(f"chunks: {count}")
        return
    runtime = await build_runtime(settings)
    if args.command == "run":
        result = await runtime.run(args.question, thread_id=args.thread_id)
        runtime.tracer.flush()
        print(f"action: {result.action}")
        if result.sources:
            print("sources: " + ", ".join(result.sources))
        if result.tool_name:
            print(f"tool: {result.tool_name}")
        if result.trace_id:
            print(f"trace: {result.trace_id}")
        print("---")
        print(result.answer)
        return
    if args.command == "graph":
        print(runtime.graph.get_graph().draw_mermaid())
        return
    if args.command == "eval":
        cases = load_golden(settings.golden_file.read_text(encoding="utf-8"))
        sink = LangfuseScoreSink() if runtime.tracer.enabled else NullScoreSink()
        report = await run_eval(runtime, cases, sink)
        runtime.tracer.flush()
        for row in report.rows:
            status = "pass" if row.passed else "fail"
            detail = ", ".join(row.failures)
            suffix = f" ({detail})" if detail else ""
            print(f"{status} {row.case_id} action={row.action}{suffix}")
        print(f"{report.passed} passed, {report.failed} failed")
        if report.failed:
            raise SystemExit(1)
        return
    raise RuntimeError(f"unknown command: {args.command}")


def _serve(host: str, port: int) -> None:
    import uvicorn

    from knowhow.web.app import create_app

    uvicorn.run(create_app(), host=host, port=port)
