"""Isolated settings for tests. The developer machine may already export provider keys."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clear_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(("KNOWHOW_", "OPENAI_", "LANGFUSE_")):
            monkeypatch.delenv(key, raising=False)
