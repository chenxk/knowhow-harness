# MCP

Knowhow 是 MCP 客户端：设置里贴 Cursor / Claude 那种 `mcpServers` JSON，解析后写到 `.knowhow/mcp.json`，再用 `langchain-mcp-adapters` 的 `MultiServerMCPClient` 去连。`servers/notes_mcp.py` 是本仓库自带的服务端示例，独立进程，不 import `knowhow`。

下面用的名字都是仓库里真实的模块和依赖。`pyproject.toml` 里和 MCP 有关的依赖是 `mcp>=1.9` 和 `langchain-mcp-adapters>=0.1`。服务端示例写的是 `from mcp.server.fastmcp import FastMCP`，这个类在 `mcp` 包里。

## 技术栈

语言是 Python 3.12+。

| 角色 | 库 | 在本仓库 |
| --- | --- | --- |
| 协议与传输 | `mcp` | 客户端会话 `mcp.client.session.ClientSession`；stdio / SSE / streamable HTTP 分别在 `mcp.client.stdio`、`mcp.client.sse`、`mcp.client.streamable_http` |
| 服务端 | `mcp.server.fastmcp.FastMCP` | `servers/notes_mcp.py`，`mcp.run(transport="stdio")` |
| 接进 Agent | `langchain_mcp_adapters.client.MultiServerMCPClient` | `src/knowhow/tools/catalog.py` 的 `McpToolCatalog.reload` |

本仓库认三种传输，类型是 `mcp_config.Transport`：`"stdio"`、`"http"`、`"sse"`。带 `url` 且没写 `type` / `transport` 时，`_document_transport` 记成 `"http"`。`McpServer.connection()` 把 `"http"` 交给适配器时字段仍是 `"transport": "http"`，适配器 `create_session` 把 `"http"`、`"streamable_http"`、`"streamable-http"` 都走 streamable HTTP。因此没写类型的 `url` 一律按 streamable HTTP 连。这类端点的路径现在通常以 `/mcp` 结尾。

### 配置放哪、长什么样

用户贴进来的是 `mcpServers` 对象，由 `parse_mcp_document` / `apply_mcp_document` 合并进磁盘。落盘文件是 `.knowhow/mcp.json`（`Settings.mcp_store`，整份 `.knowhow/` 已 gitignore），形状是本仓库自己的 `servers` 数组，和贴进来的 JSON 不一样。

贴进设置、用 stdio 拉起示例进程：

```json
{
  "mcpServers": {
    "notes": {
      "command": "uv",
      "args": ["run", "python", "servers/notes_mcp.py"]
    }
  }
}
```

没写 `type`、有 `command`，传输是 stdio。`knowhow serve` 的工作目录需要是仓库根，相对路径 `servers/notes_mcp.py` 才找得到。同一份条目也写在 `config/mcp.yaml` 的 `notes` 下，但那份 yaml 只在 `KNOWHOW_MCP_ENABLED=true` 时由 `runtime._mcp_servers` 合并进来。设置里的 `.knowhow/mcp.json` 每次启动都会读，不看这个开关。同名时用户文件覆盖 yaml（`merge_servers`）。

远程 streamable HTTP，`Authorization` 用示例 token：

```json
{
  "mcpServers": {
    "demo": {
      "url": "https://example.invalid/mcp",
      "headers": {
        "Authorization": "Bearer example-token"
      }
    }
  }
}
```

没写 `type`、有 `url`，传输是 `"http"`，也就是 streamable HTTP。旧的 HTTP+SSE 必须写明类型，例如 `"type": "sse"`（`"transport": "sse"` 同样认）。`disabled: true` 会存成 `enabled: false`。

保存之后磁盘上大致是：

```json
{
  "servers": [
    {
      "name": "notes",
      "enabled": true,
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "python", "servers/notes_mcp.py"],
      "url": "",
      "env": {},
      "headers": {}
    }
  ]
}
```

stdio 用 `command` / `args` / `env`；HTTP 用 `url` / `headers`。另一侧的字段留空，`connection()` 也不会带上。

## 协议里实际走的几步

线上是 JSON-RPC 2.0：请求有 `jsonrpc`、`id`、`method`、`params`；通知没有 `id`，也没有响应。本客户端用到的方法按顺序是：

1. `initialize`。`ClientSession.initialize` 发出，带 `protocolVersion`（SDK 的 `LATEST_PROTOCOL_VERSION`）、`capabilities`、`clientInfo`。服务器回 `InitializeResult`（协议版本、能力、serverInfo）。版本不在 SDK 支持列表里会抛 `RuntimeError`，后面的通知不会发。
2. `notifications/initialized`。同一次 `initialize()` 里，在结果校验通过之后发出。通知，没有响应。
3. `tools/list`。`langchain_mcp_adapters.tools.load_mcp_tools` 先 `await session.initialize()`，成功后才 `_list_all_tools` → `session.list_tools()`。握手失败时这个调用不会发生，所以日志里看不到 `tools/list`。
4. `tools/call`。发生在后一次连接上，见文末「工具怎么进目录」。

在本仓库：列工具发生在 `McpToolCatalog.reload` → `MultiServerMCPClient.get_tools`。`get_tools` 为这次列表单独开一个会话，列完就关掉。调用工具时适配器再开一个新会话，再握一次手，然后 `call_tool`。列表会话不会留着给下一轮调用。

`tools/list` 里每个工具至少有这三项（`mcp.types.Tool`，FastMCP 在 `list_tools` 里填）：

- `name`：函数名，示例里是 `lookup_note`、`current_time`、`learn_agent`。
- `description`：函数 docstring。`lookup_note` 的描述是 `Look up a short operational note by topic.`
- `inputSchema`：由参数注解生成的 JSON Schema。对 `servers/notes_mcp.py` 做 stdio `tools/list`，`lookup_note` 的 schema 是：

```json
{
  "type": "object",
  "properties": {
    "topic": { "title": "Topic", "type": "string" }
  },
  "required": ["topic"],
  "title": "lookup_noteArguments"
}
```

`current_time` 没有参数，`properties` 是空对象。`learn_agent` 的 `topic` 有默认值 `""`，所以不在 `required` 里。

## 三种传输

**stdio。** 本机子进程，JSON-RPC 走 stdin / stdout。没有 HTTP，也没有 `mcp-session-id`。适合 `notes_mcp.py` 这种跟 Agent 一起起、一起停的进程。配置是 `command` + `args`。示例进程末尾是 `mcp.run(transport="stdio")`。

**SSE。** 旧的 HTTP 传输：客户端先连 SSE，服务器再给出用来 POST 的 endpoint，会话 id 经常在这个 URL 的 query 里（`mcp.client.sse` 读 `sessionId` 或 `session_id`）。本仓库只有在 JSON 里写了 `"type": "sse"` 或 `"transport": "sse"` 时才走它。仓库里没有 SSE 服务端示例。

**streamable HTTP。** 现在的 HTTP 传输，一个 URL（常见以 `/mcp` 结尾）上 POST JSON-RPC，响应可以是单份 JSON，也可以是 SSE。本仓库对「有 `url`、没写类型」的服务默认用它。客户端实现是 `mcp.client.streamable_http`。

### streamable HTTP 的会话

传输对象一开始 `session_id` 是空的。`initialize` 这次 POST 不带 `mcp-session-id`。服务器如果在这次响应头里给出 `mcp-session-id`，客户端存下来，之后的 POST（包括 `tools/list`、`tools/call`）以及服务端推送用的 GET，都会带上这个头。协商出的协议版本之后也会放进 `mcp-protocol-version`。请求同时带 `Accept: application/json, text/event-stream` 和 `Content-Type: application/json`。

握手失败时还没发 `tools/list`，是因为列表写在 `await session.initialize()` 的后面：HTTP 错误、协议版本不对、会话在 `initialize` 返回前被关掉，都会在 `load_mcp_tools` 里抛出去，`list_tools` 不会被调用。会话头也是从这次 `initialize` 的响应里取的，握手没完成就没有 `mcp-session-id` 可带。`McpToolCatalog.reload` 抓住这个异常，记到该服务的 `error`，然后继续下一个服务。

### headers

`headers` 在 `McpServer.connection()` 里原样放进适配器的连接项，再交给 httpx，连接期间每次 HTTP 请求都带上，包括 `Authorization`。`GET /api/mcp` 的 `McpServerOut` 只回 `has_headers: true/false`，不回 header 的内容。设置页据此显示「已配置请求头」。出错文案走 `public_error`：header 值长度 ≥ 8 的会被换成 `******`。

## 名字冲突、停用、连不上

内置工具名是 `current_time`、`learn_agent`、`lookup_note`（`StaticToolCatalog.names`）。MCP 工具先经过 `unique_tool_name`：名字还没被占用就原样注册；占用了就加服务名前缀 `{server}_{tool}`，还占用就再加 `_2`、`_3`。`notes` 这个示例的三个工具和内置重名，连上之后目录里的名字是 `notes_lookup_note`、`notes_current_time`、`notes_learn_agent`。路由和 `act` 用的是加前缀之后的名字。

`disabled: true` 时 `reload` 只记一条 `enabled: false` 的状态，不调用 `get_tools`，不注册工具。某个服务 `get_tools` 抛错时同样跳过，内置工具仍在 `HybridToolCatalog.names()` 里。`ainvoke` 先查内置名字，再查 MCP。

## 跑示例

`servers/notes_mcp.py` 用 FastMCP 注册了上面三个工具。在仓库根目录用 stdio 拉起（进程会停在 stdin 上等客户端，自己不打印工具列表）：

```text
.venv\Scripts\python.exe servers\notes_mcp.py
```

`uv run python servers/notes_mcp.py` 等价，也是 `config/mcp.yaml` 里的启动方式。用仓库 `.venv` 里的 `mcp` 客户端对这个进程做一次 stdio `initialize` 再 `tools/list`（不访问外网），能列出 `lookup_note`、`current_time`、`learn_agent`，协议版本 `2025-11-25`。

贴进设置的就是上面那份 `notes` 的 `mcpServers`。保存后服务名是 `notes`，工具名因为和内置冲突会带前缀。

## 工具怎么进目录

`build_runtime` 建 `HybridToolCatalog`，然后 `reload_mcp(_mcp_servers(...))`。`_mcp_servers` 始终读 `.knowhow/mcp.json`；只有 `KNOWHOW_MCP_ENABLED=true` 才再读 `config/mcp.yaml`。每个 `enabled` 的服务用自己的 `connection()` 建一个 `MultiServerMCPClient`，`get_tools(server_name=...)` 完成握手和 `tools/list`，再按上一节的规则放进目录。

设置里保存走 `POST /api/mcp/import`（或单条 `POST /api/mcp`）：先写文件，再 `Runtime.reload_mcp`，响应返回时目录已经换过。下一轮 `decide` 看到的 `catalog.names()` 包含这些名字（offline 按工具名匹配，live 写进路由提示词）。选中后 `graph` 的 `act` 节点调用 `catalog.ainvoke`。MCP 工具走 LangChain 的 `ainvoke`，适配器新开一个会话，再 `initialize`，再 `tools/call`。路由约定里 `tool_args` 是字符串到字符串，调用时原样传给工具。
