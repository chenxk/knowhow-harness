"""Tool catalogs behind one invoke surface."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml
from langchain_mcp_adapters.client import MultiServerMCPClient

from knowhow.tools.clock import current_time_text
from knowhow.tools.learn import learn_agent_text
from knowhow.tools.mcp_config import McpServer, public_error

_LOG = logging.getLogger(__name__)


class ToolCatalog(Protocol):
    """Named tools the router may select."""

    async def setup(self) -> None:
        """Connect remote servers. Local catalogs do nothing."""

    def names(self) -> list[str]:
        """Tool names visible to the router."""

    async def ainvoke(self, name: str, args: dict[str, str]) -> str:
        """Run one tool and return its text result."""


class StaticToolCatalog:
    """Offline stand-in for `servers/notes_mcp.py`'s tools."""

    async def setup(self) -> None:
        return None

    def names(self) -> list[str]:
        return ["current_time", "learn_agent", "lookup_note"]

    async def ainvoke(self, name: str, args: dict[str, str]) -> str:
        if name == "current_time":
            return current_time_text()
        if name == "learn_agent":
            return learn_agent_text(args.get("topic", ""))
        if name == "lookup_note":
            topic = args.get("topic", "")
            return (
                f"lookup_note result for {topic}: check the oncall note, then the Langfuse trace."
            )
        raise KeyError(name)


def load_mcp_servers(path: Path) -> dict[str, dict[str, object]]:
    """Read the MultiServerMCPClient server map."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not loaded:
        raise RuntimeError(f"MCP config must be a non-empty mapping: {path}")
    servers: dict[str, dict[str, object]] = {}
    for name, spec in loaded.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            raise RuntimeError(f"MCP server {name!r} in {path} must be a mapping")
        servers[name] = spec
    return servers


class _McpClient(Protocol):
    async def get_tools(self, *, server_name: str | None = None) -> list[object]:
        """Return tools for one server, or every server when the name is omitted."""


McpClientFactory = Callable[[dict[str, dict[str, object]]], _McpClient]


@dataclass(frozen=True)
class McpServerStatus:
    """Connection outcome for one configured server."""

    name: str
    enabled: bool
    connected: bool
    tool_count: int
    tools: tuple[str, ...]
    error: str


def _default_client(connections: dict[str, dict[str, object]]) -> _McpClient:
    return MultiServerMCPClient(connections)  # type: ignore[arg-type]


def unique_tool_name(tool_name: str, server_name: str, taken: set[str]) -> str:
    """Keep a free name, otherwise prefix the server so builtins are not replaced."""
    if tool_name not in taken:
        return tool_name
    prefixed = f"{server_name}_{tool_name}"
    if prefixed not in taken:
        return prefixed
    index = 2
    while f"{prefixed}_{index}" in taken:
        index += 1
    return f"{prefixed}_{index}"


class McpToolCatalog:
    """LangChain tools loaded from configured MCP servers."""

    def __init__(
        self,
        *,
        reserved: set[str] | None = None,
        client_factory: McpClientFactory | None = None,
    ) -> None:
        self._reserved = set(reserved or ())
        self._factory = client_factory or _default_client
        self._tools: dict[str, object] = {}
        self._owners: dict[str, McpServer] = {}
        self._status: list[McpServerStatus] = []

    async def setup(self) -> None:
        return None

    def names(self) -> list[str]:
        return list(self._tools)

    def status(self) -> list[McpServerStatus]:
        return list(self._status)

    async def reload(self, servers: list[McpServer]) -> None:
        """Connect enabled servers. A failed server is recorded and skipped."""
        tools: dict[str, object] = {}
        owners: dict[str, McpServer] = {}
        status: list[McpServerStatus] = []
        taken = set(self._reserved)
        for server in servers:
            if not server.enabled:
                status.append(
                    McpServerStatus(
                        name=server.name,
                        enabled=False,
                        connected=False,
                        tool_count=0,
                        tools=(),
                        error="",
                    )
                )
                continue
            try:
                client = self._factory({server.name: server.connection()})
                loaded = await client.get_tools(server_name=server.name)
            except Exception as exc:
                _LOG.warning("MCP server %s failed (%s)", server.name, type(exc).__name__)
                status.append(
                    McpServerStatus(
                        name=server.name,
                        enabled=True,
                        connected=False,
                        tool_count=0,
                        tools=(),
                        error=public_error(exc, server),
                    )
                )
                continue
            registered: list[str] = []
            for tool in loaded:
                raw_name = getattr(tool, "name", "")
                if not isinstance(raw_name, str) or not raw_name:
                    continue
                name = unique_tool_name(raw_name, server.name, taken)
                tools[name] = tool
                owners[name] = server
                taken.add(name)
                registered.append(name)
            status.append(
                McpServerStatus(
                    name=server.name,
                    enabled=True,
                    connected=True,
                    tool_count=len(registered),
                    tools=tuple(registered),
                    error="",
                )
            )
        self._tools = tools
        self._owners = owners
        self._status = status

    async def ainvoke(self, name: str, args: dict[str, str]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        try:
            result = await _invoke(tool, args)
        except Exception as exc:
            owner = self._owners.get(name)
            _LOG.warning("MCP tool %s failed (%s)", name, type(exc).__name__)
            detail = public_error(exc, owner) if owner is not None else type(exc).__name__
            return f"工具调用失败：{detail}"
        return result


class HybridToolCatalog:
    """Builtin tools plus MCP tools. Disabled or failed servers add nothing."""

    def __init__(self, *, client_factory: McpClientFactory | None = None) -> None:
        self._static = StaticToolCatalog()
        self._mcp = McpToolCatalog(
            reserved=set(self._static.names()),
            client_factory=client_factory,
        )

    async def setup(self) -> None:
        await self._static.setup()

    def names(self) -> list[str]:
        return [*self._static.names(), *self._mcp.names()]

    async def reload_mcp(self, servers: list[McpServer]) -> None:
        await self._mcp.reload(servers)

    def mcp_status(self) -> list[McpServerStatus]:
        return self._mcp.status()

    async def ainvoke(self, name: str, args: dict[str, str]) -> str:
        if name in self._static.names():
            return await self._static.ainvoke(name, args)
        if name in self._mcp.names():
            return await self._mcp.ainvoke(name, args)
        return f"没有这个工具：{name}"


async def _invoke(tool: object, args: dict[str, str]) -> str:
    invoke = getattr(tool, "ainvoke", None)
    if invoke is None:
        raise RuntimeError("tool has no ainvoke")
    result = await invoke(dict(args))
    if isinstance(result, tuple):
        result = result[0] if result else ""
    return result if isinstance(result, str) else str(result)
