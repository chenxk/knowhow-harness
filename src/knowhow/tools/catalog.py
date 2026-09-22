"""Tool catalogs behind one invoke surface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import yaml
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from knowhow.tools.clock import current_time_text
from knowhow.tools.learn import learn_agent_text


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


class McpToolCatalog:
    """LangChain tools loaded from one MCP client config."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._client: MultiServerMCPClient | None = None
        self._tools: dict[str, BaseTool] = {}

    async def setup(self) -> None:
        self._client = MultiServerMCPClient(load_mcp_servers(self._path))
        tools = await self._client.get_tools()
        self._tools = {tool.name: tool for tool in tools}

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def ainvoke(self, name: str, args: dict[str, str]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        result = await tool.ainvoke(dict(args))
        return result if isinstance(result, str) else str(result)
