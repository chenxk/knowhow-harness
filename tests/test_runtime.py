import pytest

from knowhow.config import Settings
from knowhow.runtime import build_runtime


@pytest.mark.asyncio
async def test_offline_routes() -> None:
    runtime = await build_runtime(Settings(_env_file=None, mode="offline"))
    password = await runtime.run("如何重置密码", thread_id="password")
    tool = await runtime.run("lookup_note 重置密码", thread_id="tool")
    hello = await runtime.run("你好", thread_id="hello")

    assert password.action == "retrieve"
    assert password.sources == ("password-reset.md",)
    assert "重置密码" in password.answer

    assert tool.action == "tool"
    assert tool.tool_name == "lookup_note"
    assert "lookup_note result" in tool.answer

    assert hello.action == "answer"
    assert hello.sources == ()
    assert "没有检索到资料" in hello.answer


@pytest.mark.asyncio
async def test_mermaid_lists_branches() -> None:
    runtime = await build_runtime(Settings(_env_file=None, mode="offline"))
    diagram = runtime.graph.get_graph().draw_mermaid()
    for name in ("decide", "retrieve", "act", "respond"):
        assert name in diagram
