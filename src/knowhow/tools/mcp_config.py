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
    headers: dict[str, str] = Field(default_factory=dict)

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
        payload = {
            "transport": "sse" if self.transport == "sse" else "http",
            "url": self.url.strip(),
        }
        if self.headers:
            payload["headers"] = dict(self.headers)
        return payload


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
        updates: dict[str, object] = {}
        if item.env and not server.env:
            updates["env"] = dict(item.env)
        if item.headers and not server.headers:
            updates["headers"] = dict(item.headers)
        kept = server.model_copy(update=updates) if updates else server
        replaced.append(kept)
    if not found:
        replaced.append(server)
    save_user_servers(path, replaced)
    return replaced


def apply_mcp_document(path: Path, document: str) -> list[McpServer]:
    """Merge a Cursor/Claude `mcpServers` document. Invalid input writes nothing."""
    incoming = parse_mcp_document(document)
    current, error = load_user_servers(path)
    if error:
        raise ValueError(error)
    by_name = {item.name: item for item in current}
    order = [item.name for item in current]
    for server in incoming:
        if server.name not in by_name:
            order.append(server.name)
        by_name[server.name] = server
    replaced = [by_name[name] for name in order]
    save_user_servers(path, replaced)
    return replaced


def parse_mcp_document(document: str) -> list[McpServer]:
    """Parse `mcpServers` JSON. Raises ValueError in Chinese and does not touch disk."""
    text = document.strip()
    if not text:
        raise ValueError("请贴入 mcpServers JSON")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("JSON 无法解析") from None
    if not isinstance(loaded, dict) or "mcpServers" not in loaded:
        raise ValueError("顶层需要 mcpServers 对象")
    raw = loaded["mcpServers"]
    if not isinstance(raw, dict):
        raise ValueError("mcpServers 需要是对象")
    if not raw:
        raise ValueError("mcpServers 里没有服务")
    servers: list[McpServer] = []
    for name, spec in raw.items():
        if not isinstance(name, str):
            raise ValueError("服务名需要是字符串")
        servers.append(_server_from_document_entry(name, spec))
    return servers


def _server_from_document_entry(name: str, spec: object) -> McpServer:
    if not isinstance(spec, dict):
        raise ValueError(f"{name} 需要是对象")
    url = _optional_str(spec.get("url"), f"{name} 的 url")
    command = _optional_str(spec.get("command"), f"{name} 的 command")
    args = _optional_str_list(spec, "args", f"{name} 的 args")
    headers = _optional_str_dict(spec, "headers", f"{name} 的 headers")
    env = _optional_str_dict(spec, "env", f"{name} 的 env")
    disabled = _disabled_flag(name, spec)
    transport = _document_transport(name, spec, url=url, command=command)
    if transport == "stdio" and not command:
        raise ValueError(f"{name} 需要 url 或 command")
    if transport != "stdio" and not url:
        raise ValueError(f"{name} 需要 url 或 command")
    server = McpServer(
        name=name,
        enabled=not disabled,
        transport=transport,
        command=command if transport == "stdio" else "",
        args=args if transport == "stdio" else [],
        url=url if transport != "stdio" else "",
        env=env if transport == "stdio" else {},
        headers=headers if transport != "stdio" else {},
    )
    try:
        validate_server(server)
    except ValueError as exc:
        raise ValueError(f"{name}：{exc}") from None
    return server


def _optional_str(value: object, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} 需要是字符串")
    return value.strip()


def _optional_str_list(spec: dict[str, object], key: str, label: str) -> list[str]:
    if key not in spec or spec[key] is None:
        return []
    value = spec[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} 需要是字符串数组")
    return [item for item in value if isinstance(item, str)]


def _optional_str_dict(spec: dict[str, object], key: str, label: str) -> dict[str, str]:
    if key not in spec or spec[key] is None:
        return {}
    value = spec[key]
    if not isinstance(value, dict):
        raise ValueError(f"{label} 需要是对象")
    result: dict[str, str] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not isinstance(item_value, str):
            raise ValueError(f"{label} 的键和值需要是字符串")
        result[item_key] = item_value
    return result


def _disabled_flag(name: str, spec: dict[str, object]) -> bool:
    if "disabled" not in spec or spec["disabled"] is None:
        return False
    disabled = spec["disabled"]
    if not isinstance(disabled, bool):
        raise ValueError(f"{name} 的 disabled 需要是 true 或 false")
    return disabled


def _document_transport(name: str, spec: dict[str, object], *, url: str, command: str) -> Transport:
    raw = spec.get("type", spec.get("transport"))
    if raw is None or raw == "":
        if url:
            return "http"
        if command:
            return "stdio"
        raise ValueError(f"{name} 需要 url 或 command")
    if not isinstance(raw, str):
        raise ValueError(f"{name} 的传输类型无法识别")
    kind = raw.strip().lower().replace("-", "_")
    if kind in {"http", "streamable_http"}:
        return "http"
    if kind == "sse":
        return "sse"
    if kind == "stdio":
        return "stdio"
    raise ValueError(f"{name} 的传输类型无法识别")


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
    text = _format_exception(exc)
    for secret in _sensitive(server):
        text = text.replace(secret, "******")
    if len(text) > 400:
        text = text[:400] + "…"
    return text


def _format_exception(exc: BaseException) -> str:
    """One line, with ExceptionGroup children so TaskGroup does not hide the cause."""
    message = str(exc).replace("\n", " ").strip()
    label = type(exc).__name__
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        nested = "; ".join(_format_exception(sub) for sub in exc.exceptions)
        if message:
            return f"{label}: {message}: {nested}"
        return f"{label}: {nested}"
    if not message:
        return label
    return f"{label}: {message}"


def _sensitive(server: McpServer) -> list[str]:
    values = [arg for arg in server.args if len(arg) >= 8]
    values.extend(value for value in server.env.values() if len(value) >= 8)
    values.extend(value for value in server.headers.values() if len(value) >= 8)
    url = server.url.strip()
    if "?" in url:
        values.append(url.split("?", 1)[1])
    return values
