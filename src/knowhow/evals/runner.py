"""Golden-file evaluation over one runtime."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from knowhow.runtime import Runtime
from knowhow.types import Action


class EvalCase(BaseModel):
    id: str
    question: str
    expect_action: Action
    expect_source: str = ""
    expect_tool: str = ""
    expect_answer_contains: str = ""
    thread_id: str = ""
    clear_memories: bool = False


class GoldenFile(BaseModel):
    cases: list[EvalCase] = Field(min_length=1)


class CaseResult(BaseModel):
    case_id: str
    passed: bool
    action: Action
    sources: tuple[str, ...] = ()
    tool_name: str = ""
    trace_id: str | None = None
    failures: tuple[str, ...] = ()


class EvalReport(BaseModel):
    rows: tuple[CaseResult, ...]

    @property
    def passed(self) -> int:
        return sum(1 for row in self.rows if row.passed)

    @property
    def failed(self) -> int:
        return len(self.rows) - self.passed


class ScoreSink(Protocol):
    """Receive a finished report. Local runs can ignore it."""

    def record(self, report: EvalReport) -> None:
        """Persist scores. Implementations may no-op when trace ids are absent."""


class NullScoreSink:
    def record(self, report: EvalReport) -> None:
        del report


class LangfuseScoreSink:
    """Write one boolean `case_pass` score per case that has a trace id."""

    def record(self, report: EvalReport) -> None:
        from langfuse import get_client

        client = get_client()
        for row in report.rows:
            if not row.trace_id:
                continue
            comment = row.case_id
            if row.failures:
                comment = f"{row.case_id}: {'; '.join(row.failures)}"
            client.create_score(
                name="case_pass",
                value=1.0 if row.passed else 0.0,
                trace_id=row.trace_id,
                data_type="BOOLEAN",
                comment=comment,
            )
        client.flush()


def load_golden(text: str) -> list[EvalCase]:
    """Parse a golden YAML document."""
    import yaml

    loaded = yaml.safe_load(text)
    return GoldenFile.model_validate(loaded).cases


async def run_eval(
    runtime: Runtime,
    cases: list[EvalCase],
    sink: ScoreSink | None = None,
) -> EvalReport:
    rows: list[CaseResult] = []
    for case in cases:
        if case.clear_memories:
            for item in runtime.memory.list():
                runtime.memory.soft_delete(item.id)
        thread_id = case.thread_id or f"eval-{case.id}"
        result = await runtime.run(case.question, thread_id=thread_id)
        failures = _failures(case, result.action, result.sources, result.tool_name, result.answer)
        rows.append(
            CaseResult(
                case_id=case.id,
                passed=not failures,
                action=result.action,
                sources=result.sources,
                tool_name=result.tool_name,
                trace_id=result.trace_id,
                failures=tuple(failures),
            )
        )
    report = EvalReport(rows=tuple(rows))
    (sink or NullScoreSink()).record(report)
    return report


def _failures(
    case: EvalCase,
    action: Action,
    sources: tuple[str, ...],
    tool_name: str,
    answer: str,
) -> list[str]:
    failures: list[str] = []
    if action != case.expect_action:
        failures.append(f"action {action} != {case.expect_action}")
    if case.expect_source and case.expect_source not in sources:
        failures.append(f"missing source {case.expect_source}")
    if case.expect_tool and tool_name != case.expect_tool:
        failures.append(f"tool {tool_name} != {case.expect_tool}")
    if case.expect_answer_contains and case.expect_answer_contains not in answer:
        failures.append(f"answer missing {case.expect_answer_contains!r}")
    return failures
