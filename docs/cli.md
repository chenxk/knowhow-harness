# CLI

这篇说明 `knowhow` 怎么解析参数、怎么把一次提问送进 `Runtime`，以及配置校验失败时进程怎么退出。对象是要改命令行的人。可复制的日常命令仍在 README 的「命令」一节。

## 技术栈

| 项 | 实际用法 |
| --- | --- |
| Python | `pyproject.toml` 的 `requires-python = ">=3.12"`，Ruff `target-version = "py312"` |
| CLI 库 | 标准库 `argparse`（`src/knowhow/cli.py`）。`dependencies` 里没有 Click 或 Typer |
| 配置 | `knowhow.config.Settings`，继承 `pydantic_settings.BaseSettings` |
| HTTP | `serve` 用 `uvicorn.run` 跑 `knowhow.web.app.create_app`（FastAPI） |
| 一次提问 | `run` / `eval` / `graph` 走 `knowhow.runtime.build_runtime` |

`Settings` 的加载约定在 `src/knowhow/config.py`：

- `env_prefix="KNOWHOW_"`，字段 `mode` 对应环境变量 `KNOWHOW_MODE`，`chat_model` 对应 `KNOWHOW_CHAT_MODEL`，其余字段同理。
- `env_file=".env"`，相对**当前工作目录**。`extra="ignore"`，多出来的变量不报错。
- 凭证沿用常见名字，用 `AliasChoices` 同时接受带前缀和不带前缀的名字：`OPENAI_API_KEY` / `KNOWHOW_OPENAI_API_KEY`，`OPENAI_BASE_URL` / `KNOWHOW_OPENAI_BASE_URL`，以及 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_HOST`、`LANGFUSE_PROJECT_ID`。
- 默认 `mode="offline"`。相对路径（语料、skills、golden、会话目录、记忆文件）在 `corpus_path` 这类属性里经 `_resolve` 接到 `project_root()`：从 `config.py` 向上找到含 `pyproject.toml` 的目录。这和 `.env` 的 cwd 相对路径不是同一套。

CLI 自己不读配置文件格式。`main` 里 `Settings()` 无参构造，环境变量和 `.env` 由 pydantic-settings 填进去。

## 入口怎么注册成命令

`pyproject.toml`：

```toml
[project.scripts]
knowhow = "knowhow.cli:main"
```

setuptools 据此生成控制台脚本，指向 `src/knowhow/cli.py` 的 `main`。装进当前虚拟环境后，Windows 上是 `.venv\Scripts\knowhow.exe`。仓库文档里的日常写法是在根目录执行 `uv run knowhow ...`。

源码树没有 `src/knowhow/__main__.py`。`python -m knowhow` 会失败：`No module named knowhow.__main__`。`cli.py` 也没有 `if __name__ == "__main__"`，`python -m knowhow.cli` 不会调用 `main`。要绕过脚本直接打帮助：

```powershell
.venv\Scripts\python.exe -c "from knowhow.cli import main; main(['--help'])"
```

`main(argv=None)` 把列表交给 `ArgumentParser.parse_args`。`argv` 为 `None` 时 argparse 使用 `sys.argv[1:]`。

## 参数解析和子命令

`main` 建一个解析器，`prog="knowhow"`，`description="Knowhow agent runtime"`，然后：

```python
sub = parser.add_subparsers(dest="command", required=True)
```

用 `.venv\Scripts\knowhow.exe --help` 核对过的子命令是 `run`、`ingest`、`eval`、`graph`、`serve`。帮助文案是 `add_parser(..., help=...)` 上的中文；argparse 自己的 “usage / options” 仍是英文。解析器没有 `ArgumentDefaultsHelpFormatter`，`--help` 不打印默认值，默认值写在 `add_argument` 上。

| 子命令 | help | 参数 |
| --- | --- | --- |
| `run` | 回答一个问题 | 位置参数 `question`；`--thread-id`，默认 `"cli"` |
| `ingest` | 把 data/corpus 编进内存索引并打印块数 | 无 |
| `eval` | 跑 evals/golden.yaml | 无 |
| `graph` | 打印 LangGraph mermaid | 无 |
| `serve` | 启动工作台 | `--host` 默认 `127.0.0.1`；`--port` 为 `int`，默认 `8765` |

`serve` 在 `parse_args` 之后立刻 `_serve` 并 `return`，不进入下面的 `asyncio.run(_dispatch)`。其余命令进 `_dispatch`。

缺子命令、未知子命令、`--port` 不是整数，都由 argparse 自己 `SystemExit(2)`，用法说明在 stderr。`_dispatch` 末尾的 `raise RuntimeError(f"unknown command: {args.command}")` 是解析结果对不上分支时的兜底；`required=True` 的子命令解析正常不会走到那里。

## serve：FastAPI、uvicorn、静态资源

```python
def _serve(host: str, port: int) -> None:
    import uvicorn
    from knowhow.web.app import create_app

    uvicorn.run(create_app(), host=host, port=port)
```

`uvicorn` 和 `create_app` 放在函数内部导入，只有 `serve` 才加载 Web 栈。

`create_app`（`src/knowhow/web/app.py`）创建 `FastAPI(title="Knowhow")`。lifespan 里如果调用方没有传入 `Runtime`，就 `await build_runtime()`：校验配置、把语料编进内存索引、编译图，都发生在 uvicorn 启动阶段，而不是 `cli.py` 的 `_dispatch`。

静态目录是包内的 `src/knowhow/web/static/`（`Path(__file__).with_name("static")`）。`frontend/vite.config.ts` 把生产构建写到同一处：

```ts
build: {
  outDir: '../src/knowhow/web/static',
  emptyOutDir: true,
},
```

`pnpm --dir frontend build` 之后若存在 `static/index.html`，`GET /` 返回这个文件；存在 `static/assets/` 时再 `app.mount("/assets", StaticFiles(...))`。没有 `index.html` 时 `GET /` 返回纯文本：

```text
前端尚未构建。请运行：pnpm --dir frontend build
```

`/api/*` 的注册不依赖这份构建产物。`pyproject.toml` 的 `package-data` 包含 `web/static/**`，装好的包可以带上已构建的 SPA。

Vite 开发服务器是另一个进程。`pnpm --dir frontend dev` 听 `5173`，把 `/api` 代理到 `http://127.0.0.1:8765`。`knowhow serve` 不启动 Vite。

`serve` 不经过 `main` 里 `except RuntimeError` 那段。`Settings.check()` 在 lifespan 里失败时，异常由 uvicorn 打出，不会先在 stderr 打印 `error:` 再 `SystemExit(2)`。

## run：一次提问怎么进 Runtime

`_dispatch` 对 `run`、`graph`、`eval` 都是先 `settings = Settings()`，再 `runtime = await build_runtime(settings)`。`ingest` 只调用 `settings.check()` 和 `ingest_dir`，不编译图，成功时 stdout 一行 `chunks: {count}`。

`build_runtime`（`src/knowhow/runtime.py`）顺序：

1. `resolved.check()`。
2. `InMemoryStore` + `ingest_dir(store, resolved.corpus_path)`。
3. `HybridToolCatalog`，再按设置装入 MCP 服务（见文末）。
4. `mode == "live"` 时构造 `ChatOpenAI(model=chat_model, api_key=..., base_url=..., temperature=0, streaming=True)`，路由用 `ModelDecider`，回答用 `ModelResponder`。
5. 否则路由用 `ScriptedDecider`（工具名、技能触发、词法检索阈值），回答用 `OfflineResponder`。后者不调模型：有工具输出就原文返回，有检索片段就以「根据资料：」拼起来，否则是固定中文句子。
6. `build_graph` 编译 LangGraph：`decide` 之后走 `retrieve`、`act`（工具）或直接 `respond`。checkpoint 是 `MemorySaver`，只活在本进程。

`run` 分支：

```python
result = await runtime.run(args.question, thread_id=args.thread_id)
runtime.tracer.flush()
print(f"action: {result.action}")
# 有 sources / tool_name / trace_id 才各打一行
print("---")
print(result.answer)
```

`Runtime.run` 把 `stream()` 里最后一条 `type="done"` 收成 `RunResult`。stdout 标签（`action:`、`sources:`、`tool:`、`trace:`、`---`）是英文；回答正文随 offline 模板或 live 模型而定。

`graph` 在同一 runtime 上调用 `runtime.graph.get_graph().draw_mermaid()`，把 mermaid 打到 stdout。

`eval` 读取 `settings.golden_file`（默认 `evals/golden.yaml`），`run_eval` 后逐行打印 `pass` 或 `fail`，最后一行 `{passed} passed, {failed} failed`。`report.failed` 非 0 时 `raise SystemExit(1)`。`main` 只捕获 `RuntimeError`，这个退出码会原样离开进程。追踪开启时 sink 是 `LangfuseScoreSink`，否则 `NullScoreSink`。

CLI 的 `--thread-id` 只作为这次图的 checkpoint 线程 id。它不读取、不写入 `sessions.py` 的会话 JSON。

## 配置校验失败时怎么退出

`Settings.check()` 在模式和路径对不上时抛 `RuntimeError`，文案是英文：

- `mode == "live"` 且 key 去掉空白后为空：`KNOWHOW_MODE=live requires OPENAI_API_KEY`
- `KNOWHOW_MCP_ENABLED` 为真且 MCP yaml 不是文件：`MCP config not found: {path}`
- 语料目录、skills 目录、golden 文件缺失：`corpus dir not found` / `skills dir not found` / `golden file not found`，后面带解析后的路径

`run`、`ingest`、`eval`、`graph` 上，这个异常被 `main` 收成：

```python
except RuntimeError as exc:
    print(f"error: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc
```

| 情况 | 退出码 | 去向 |
| --- | --- | --- |
| 子命令正常结束 | 0 | stdout 为该命令的打印 |
| `eval` 有失败用例 | 1 | stdout 含 `fail` 行和汇总 |
| `Settings.check()` 及其它 `RuntimeError` | 2 | stderr：`error: ` 加异常文本 |
| argparse 用法错误 | 2 | stderr：argparse 用法 |
| `serve` 在 lifespan 里校验失败 | 由 uvicorn 处理 | 不走上一行的 `error:` |

用户能在终端里看到的中文，主要是子命令 `--help` 的 `help=`，以及没构建前端时 `GET /` 的那句提示。`run` / `eval` / `ingest` 的状态标签和 `error:` 前缀是英文。

## 示例

在仓库根目录执行。`serve` 的 host 和 port 写出来是为了和默认值对照，省略这两个参数效果相同。

```powershell
uv run knowhow serve --host 127.0.0.1 --port 8765
```

浏览器打开 `http://127.0.0.1:8765`。已经 `pnpm --dir frontend build` 时 `/` 是 SPA；还没构建时 `/` 是上面的中文纯文本。另开终端跑前端开发服务器：

```powershell
pnpm --dir frontend dev
```

默认离线，不需要 API key。这一次会 `build_runtime`：检查语料目录、建内存索引、按脚本路由回答。

```powershell
uv run knowhow run "如何重置密码"
```

stdout 大致是 `action:` 一行，有检索命中时还有 `sources:`，然后 `---` 和正文。

缺 key 只在 live 且 key 为空时出现。环境或当前目录 `.env` 里已经有 `OPENAI_API_KEY` 时，pydantic-settings 会读到它，不会报下面这句。PowerShell 里把本次进程的 key 清空：

```powershell
$env:KNOWHOW_MODE = "live"
$env:OPENAI_API_KEY = ""
$env:KNOWHOW_OPENAI_API_KEY = ""
uv run knowhow run "如何重置密码"
```

stderr 为 `error: KNOWHOW_MODE=live requires OPENAI_API_KEY`，退出码 2。不要把真实 key 写进 shell 历史或文档。

## 加一个子命令

同一条 `knowhow` 命令下加子命令，改 `src/knowhow/cli.py` 两处：`main` 里 `add_parser`，`_dispatch` 里按 `args.command` 分支并 `return`。`pyproject.toml` 的 `knowhow = "knowhow.cli:main"` 不用改。仓库没有另外的命令注册表。

下面不是已实现的命令，只是对齐现有写法的骨架。需要图或语料时，跟 `run` 一样 `await build_runtime(settings)`，不要在 CLI 里重写路由。

```python
# main() 内，已有的 sub.add_parser(...) 旁边：
ping = sub.add_parser("ping", help="打印一行固定文字")
ping.add_argument("--name", default="knowhow")

# _dispatch() 内，settings = Settings() 之后：
if args.command == "ping":
    print(f"pong {args.name}")
    return
```

帮助字符串用中文。新的 stdout 若要给用户看，也用中文；标识符保持英文。校验失败继续抛 `RuntimeError`，让 `main` 打 `error:` 并以 2 退出。

## 和 MCP、会话、记忆

`build_runtime` 会读 `.knowhow/mcp.json` 里启用的服务；`KNOWHOW_MCP_ENABLED=true` 时再合并 `config/mcp.yaml`（`runtime._mcp_servers`）。传输和配置见 [docs/mcp.md](mcp.md)。

Web 的会话列表和消息 JSON 在 `sessions.py`，默认目录 `.knowhow/sessions/`。`knowhow run` 只用 `--thread-id` 作为本进程 checkpoint，不写这份 JSON。见 README 的 [布局](../README.md#布局)。

`Runtime.run` 仍会按 `Settings` 召回 active 记忆，并在这一轮结束后抽取；文件默认 `.knowhow/memory.sqlite`（`KNOWHOW_MEMORY_PATH`）。晋升和删除规则见 README 的 [布局](../README.md#布局)。
