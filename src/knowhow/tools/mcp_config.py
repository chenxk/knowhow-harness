"""User MCP servers persisted in `.knowhow/mcp.json`."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
Transport = Literal["stdio", "http", "sse"]


class McpServer(BaseModel):
    """One MCP server the agent may connect to."""

    model_config = ConfigDict(extra="ignore")

    name: str
    enabled: bool = True
    transport: Transport = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)

    def connection(self) -> dict[str, object]:
        """Map this server onto a MultiServerMCPClient connection entry."""
        if self.transport == "stdio":
            payload: dict[str, object] = {
                "transport": "stdio",
                "command": self.command.strip(),
                "args": list(self.args),
            }
            if self.env:
                payload["env"] = dict(self.env)
            return payload
        if self.transport == "sse":
            return {"transport": "sse", "url": self.url.strip()}
        return {"transport": "http", "url": self.url.strip()}


def validate_server(server: McpServer) -> None:
    """Reject a server the client cannot launch."""
    if _NAME.fullmatch(server.name) is None:
        raise ValueError("名称需以字母开头，只含字母、数字、下划线和连字符")
    if server.transport == "stdio":
        if not server.command.strip():
            raise ValueError("stdio 需要填写命令")
        return
    url = server.url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL 需要以 http:// 或 https:// 开头")


def load_user_servers(path: Path) -> tuple[list[McpServer], str]:
    """Read user servers. A missing file is an empty list; a bad file does not raise."""
    if not path.is_file():
        return [], ""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], "MCP 配置无法读取"
    if not isinstance(loaded, dict):
        return [], "MCP 配置格式不正确"
    raw_servers = loaded.get("servers", [])
    if not isinstance(raw_servers, list):
        return [], "MCP 配置格式不正确"
    servers: list[McpServer] = []
    for item in raw_servers:
        if not isinstance(item, dict):
            return [], "MCP 配置格式不正确"
        try:
            server = McpServer.model_validate(item)
            validate_server(server)
        except ValueError:
            return [], "MCP 配置里有无法使用的服务"
        servers.append(server)
    return servers, ""


def save_user_servers(path: Path, servers: list[McpServer]) -> None:
    """Atomically replace the user server list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "servers": [server.model_dump() for server in servers],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def upsert_server(path: Path, server: McpServer) -> list[McpServer]:
    """Insert or replace one server and keep env values the form does not send."""
    validate_server(server)
    current, error = load_user_servers(path)
    if error:
        raise ValueError(error)
    replaced: list[McpServer] = []
    found = False
    for item in current:
        if item.name != server.name:
            replaced.append(item)
            continue
        found = True
        kept = server
        if item.env and not server.env:
            kept = server.model_copy(update={"env": dict(item.env)})
        replaced.append(kept)
    if not found:
        replaced.append(server)
    save_user_servers(path, replaced)
    return replaced


def delete_server(path: Path, name: str) -> list[McpServer]:
    """Remove one server. Missing names raise ValueError."""
    current, error = load_user_servers(path)
    if error:
        raise ValueError(error)
    kept = [item for item in current if item.name != name]
    if len(kept) == len(current):
        raise ValueError("服务不存在")
    save_user_servers(path, kept)
    return kept


def set_server_enabled(path: Path, name: str, enabled: bool) -> list[McpServer]:
    """Flip one server's enabled flag."""
    current, error = load_user_servers(path)
    if error:
        raise ValueError(error)
    found = False
    updated: list[McpServer] = []
    for item in current:
        if item.name != name:
            updated.append(item)
            continue
        found = True
        updated.append(item.model_copy(update={"enabled": enabled}))
    if not found:
        raise ValueError("服务不存在")
    save_user_servers(path, updated)
    return updated


def server_from_mapping(name: str, spec: dict[str, object]) -> McpServer:
    """Convert one MultiServerMCPClient yaml entry into a server."""
    raw_transport = spec.get("transport", "stdio")
    if raw_transport in {"streamable_http", "streamable-http"}:
        raw_transport = "http"
    if raw_transport == "stdio":
        transport: Transport = "stdio"
    elif raw_transport == "http":
        transport = "http"
    elif raw_transport == "sse":
        transport = "sse"
    else:
        raise RuntimeError(f"MCP server {name!r} uses an unsupported transport")
    args_raw = spec.get("args") or []
    args = [str(item) for item in args_raw] if isinstance(args_raw, list) else []
    env_raw = spec.get("env") or {}
    env: dict[str, str] = {}
    if isinstance(env_raw, dict):
        env = {str(key): str(value) for key, value in env_raw.items()}
    return McpServer(
        name=str(name),
        enabled=True,
        transport=transport,
        command=str(spec.get("command") or ""),
        args=args,
        url=str(spec.get("url") or ""),
        env=env,
    )


def merge_servers(base: list[McpServer], override: list[McpServer]) -> list[McpServer]:
    """Overlay `override` onto `base` by server name."""
    merged = {server.name: server for server in base}
    for server in override:
        merged[server.name] = server
    return list(merged.values())


def public_error(exc: BaseException, server: McpServer) -> str:
    """Exception text safe to show in settings. Secret-like values are redacted."""
    text = str(exc).replace("\n", " ").strip()
    for secret in _sensitive(server):
        text = text.replace(secret, "******")
    if len(text) > 200:
        text = text[:200] + "…"
    label = type(exc).__name__
    if not text:
        return label
    return f"{label}: {text}"


def _sensitive(server: McpServer) -> list[str]:
    values = [arg for arg in server.args if len(arg) >= 8]
    values.extend(value for value in server.env.values() if len(value) >= 8)
    url = server.url.strip()
    if "?" in url:
        values.append(url.split("?", 1)[1])
    return values
