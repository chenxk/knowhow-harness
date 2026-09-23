"""Isolated settings for tests. The developer machine may already export provider keys."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from knowhow.config import Settings


@pytest.fixture(autouse=True)
def _clear_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(("KNOWHOW_", "OPENAI_", "LANGFUSE_")):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_default_mcp_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Keep a developer `.knowhow/mcp.json` from being connected during tests."""
    isolated = tmp_path_factory.getbasetemp() / "empty-mcp.json"
    original = Settings.mcp_store_path.fget
    assert original is not None

    def patched(self: Settings) -> Path:
        if self.mcp_store == Path(".knowhow/mcp.json"):
            return isolated
        return original(self)

    monkeypatch.setattr(Settings, "mcp_store_path", property(patched))
