"""MCP config, registration, and settings routes. No real MCP process."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from knowhow.config import Settings
from knowhow.runtime import build_runtime
from knowhow.tools.catalog import HybridToolCatalog
from knowhow.tools.mcp_config import (
    McpServer,
    delete_server,
    load_user_servers,
    set_server_enabled,
    upsert_server,
)
from knowhow.web.app import create_app


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name

    async def ainvoke(self, args: dict[str, str]) -> str:
        return f"ran {self.name}"


def _factory(tools: dict[str, list[str] | Exception]):
    def factory(connections: dict[str, dict[str, object]]):
        class Client:
            async def get_tools(self, *, server_name: str | None = None) -> list[_Tool]:
                assert server_name is not None
                assert server_name in connections
                spec = tools[server_name]
                if isinstance(spec, Exception):
                    raise spec
                return [_Tool(name) for name in spec]

        return Client()

    return factory


def test_mcp_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    stdio = McpServer(
        name="notes",
        enabled=True,
        transport="stdio",
        command="uv",
        args=["run", "python", "servers/notes_mcp.py"],
    )
    remote = McpServer(
        name="remote",
        enabled=False,
        transport="http",
        url="http://127.0.0.1:9/mcp",
    )
    upsert_server(path, stdio)
    upsert_server(path, remote)
    loaded, error = load_user_servers(path)
    assert error == ""
    assert [item.name for item in loaded] == ["notes", "remote"]
    assert loaded[0].command == "uv"
    assert loaded[0].args == ["run", "python", "servers/notes_mcp.py"]
    assert loaded[1].enabled is False
    assert loaded[1].transport == "http"
    assert loaded[1].url == "http://127.0.0.1:9/mcp"

    set_server_enabled(path, "notes", False)
    delete_server(path, "remote")
    loaded, error = load_user_servers(path)
    assert error == ""
    assert len(loaded) == 1
    assert loaded[0].name == "notes"
    assert loaded[0].enabled is False


async def test_disabled_server_is_not_registered_and_conflicts_are_prefixed() -> None:
    secret = "super-secret-value"
    seen: list[str] = []

    def factory(connections: dict[str, dict[str, object]]):
        seen.extend(connections)
        return _factory(
            {
                "notes": ["current_time", "echo"],
                "beta": ["echo"],
                "broken": RuntimeError(f"boom {secret}"),
            }
        )(connections)

    catalog = HybridToolCatalog(client_factory=factory)
    await catalog.reload_mcp(
        [
            McpServer(name="notes", enabled=True, transport="stdio", command="uv"),
            McpServer(name="off", enabled=False, transport="stdio", command="uv"),
            McpServer(name="beta", enabled=True, transport="stdio", command="uv"),
            McpServer(
                name="broken",
                enabled=True,
                transport="stdio",
                command="uv",
                args=["--token", secret],
            ),
        ]
    )
    assert "off" not in seen
    names = catalog.names()
    assert "current_time" in names
    assert "learn_agent" in names
    assert "notes_current_time" in names
    assert "echo" in names
    assert "beta_echo" in names
    assert "off" not in names
    assert not any(name.startswith("off_") for name in names)

    status = {item.name: item for item in catalog.mcp_status()}
    assert status["off"].connected is False
    assert status["off"].tool_count == 0
    assert status["notes"].tools == ("notes_current_time", "echo")
    assert status["broken"].connected is False
    assert secret not in status["broken"].error
    assert "******" in status["broken"].error

    assert await catalog.ainvoke("echo", {}) == "ran echo"
    assert await catalog.ainvoke("current_time", {}) != "ran current_time"


def test_api_save_registers_tool_for_the_next_turn(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mode="offline",
        sessions_dir=tmp_path / "sessions",
        memory_path=tmp_path / "memory.sqlite",
        mcp_store=tmp_path / "mcp.json",
    )
    runtime = asyncio.run(
        build_runtime(settings, mcp_client_factory=_factory({"demo": ["ping"]}))
    )
    app = create_app(runtime)
    with TestClient(app) as client:
        saved = client.post(
            "/api/mcp",
            json={
                "name": "demo",
                "enabled": True,
                "transport": "stdio",
                "command": "python",
                "args": ["server.py"],
                "url": "",
            },
        )
        assert saved.status_code == 200
        row = saved.json()["servers"][0]
        assert row["connected"] is True
        assert row["tool_count"] == 1
        assert row["tools"] == ["ping"]

    result = asyncio.run(runtime.run("ping", thread_id="mcp-ping"))
    assert result.action == "tool"
    assert result.tool_name == "ping"
    assert result.answer == "ran ping"

    with TestClient(app) as client:
        disabled = client.post("/api/mcp/demo/enabled", json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json()["servers"][0]["enabled"] is False
        assert "ping" not in runtime.catalog.names()
        assert "current_time" in runtime.catalog.names()

        removed = client.delete("/api/mcp/demo")
        assert removed.status_code == 200
        assert removed.json()["servers"] == []
