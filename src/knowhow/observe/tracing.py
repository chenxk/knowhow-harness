"""Langfuse callbacks. Tracing stays off unless both keys are set."""

from __future__ import annotations

from typing import Any

from knowhow.config import Settings


class Tracer:
    """Build LangChain callbacks and flush the Langfuse client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ready = False

    @property
    def enabled(self) -> bool:
        return self._settings.tracing_enabled

    def callbacks(self) -> list[Any]:
        if not self.enabled:
            return []
        self._ensure_client()
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]

    def trace_id(self, callbacks: list[Any]) -> str | None:
        if not callbacks:
            return None
        trace_id = getattr(callbacks[0], "last_trace_id", None)
        return trace_id if isinstance(trace_id, str) and trace_id else None

    def flush(self) -> None:
        if not self._ready:
            return
        from langfuse import get_client

        get_client().flush()

    def score(
        self,
        *,
        name: str,
        value: float,
        trace_id: str,
        comment: str = "",
    ) -> None:
        """Attach one score to an existing Langfuse trace and flush."""
        if not self.enabled:
            raise RuntimeError("未启用 Langfuse，无法写 score")
        if not trace_id.strip():
            raise RuntimeError("缺少 trace id")
        self._ensure_client()
        from langfuse import get_client

        get_client().create_score(
            name=name,
            value=value,
            trace_id=trace_id,
            data_type="BOOLEAN",
            comment=comment or None,
        )
        get_client().flush()

    def _ensure_client(self) -> None:
        if self._ready:
            return
        self._settings.export_langfuse_env()
        from langfuse import Langfuse

        Langfuse(
            public_key=self._settings.langfuse_public_key,
            secret_key=self._settings.langfuse_secret_key,
            host=self._settings.langfuse_host,
        )
        self._ready = True
