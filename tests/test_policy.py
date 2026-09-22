import pytest
from langchain_core.messages import AIMessage

from knowhow.policy import ModelDecider, parse_decision
from knowhow.tools.catalog import StaticToolCatalog


class _FakeChat:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        del messages
        return AIMessage(content=self._content)


def test_parse_decision_strips_fence_and_fills_topic() -> None:
    decision = parse_decision(
        '```json\n{"action":"tool","query":"oncall","tool_name":"lookup_note"}\n```',
        question="lookup",
        tool_names={"lookup_note"},
    )
    assert decision.action == "tool"
    assert decision.tool_args["topic"] == "oncall"


def test_parse_decision_rejects_unknown_tool() -> None:
    decision = parse_decision(
        '{"action":"tool","tool_name":"missing"}',
        question="hi",
        tool_names={"lookup_note"},
    )
    assert decision.action == "answer"
    assert decision.query == "hi"


@pytest.mark.asyncio
async def test_model_decider_falls_back_when_json_is_invalid() -> None:
    decider = ModelDecider(_FakeChat("not-json"), StaticToolCatalog(), [])
    decision = await decider.decide("如何重置密码")
    assert decision.action == "answer"
    assert decision.query == "如何重置密码"
