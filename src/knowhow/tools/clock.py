"""Clock text shared by the static tool catalog."""

from __future__ import annotations

from datetime import datetime


def current_time_text() -> str:
    """Local time with a numeric offset, such as 2026-09-22T17:33:00+08:00."""
    clock = datetime.now().astimezone().isoformat(timespec="seconds")
    return f"当前时间：{clock}"
