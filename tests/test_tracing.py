from knowhow.config import Settings
from knowhow.evals.runner import CaseResult, EvalReport, LangfuseScoreSink
from knowhow.observe.tracing import Tracer


def test_langfuse_callback_can_import() -> None:
    from langfuse.langchain import CallbackHandler

    assert CallbackHandler is not None


def test_score_sink_writes_boolean_case_pass(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def create_score(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def flush(self) -> None:
            calls.append({"flush": True})

    monkeypatch.setattr("langfuse.get_client", lambda: FakeClient())
    report = EvalReport(
        rows=(
            CaseResult(
                case_id="ok",
                passed=True,
                action="answer",
                trace_id="trace-ok",
            ),
            CaseResult(
                case_id="bad",
                passed=False,
                action="tool",
                trace_id="trace-bad",
                failures=("tool x != y",),
            ),
            CaseResult(case_id="skip", passed=True, action="answer"),
        )
    )
    LangfuseScoreSink().record(report)
    scores = [item for item in calls if "name" in item]
    assert scores == [
        {
            "name": "case_pass",
            "value": 1.0,
            "trace_id": "trace-ok",
            "data_type": "BOOLEAN",
            "comment": "ok",
        },
        {
            "name": "case_pass",
            "value": 0.0,
            "trace_id": "trace-bad",
            "data_type": "BOOLEAN",
            "comment": "bad: tool x != y",
        },
    ]
    assert calls[-1] == {"flush": True}


def test_tracer_score_requires_keys() -> None:
    tracer = Tracer(Settings(_env_file=None, mode="offline"))
    try:
        tracer.score(name="user_feedback", value=1.0, trace_id="0123456789abcdef")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "Langfuse" in str(exc)
