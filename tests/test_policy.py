import pytest
from langchain_core.messages import AIMessage

from knowhow.config import project_root
from knowhow.policy import ModelDecider, match_known_tool_or_skill, parse_decision
from knowhow.skills import load_skills
from knowhow.tools.catalog import StaticToolCatalog


class _FakeChat:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = 0

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        del messages
        self.calls += 1
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


def test_match_known_tool_or_skill_hits_learn_trigger() -> None:
    skills = load_skills(project_root() / "skills")
    decision = match_known_tool_or_skill(
        "教我长期记忆怎么工作",
        "教我长期记忆怎么工作",
        catalog_names=StaticToolCatalog().names(),
        skills=skills,
    )
    assert decision is not None
    assert decision.action == "tool"
    assert decision.tool_name == "learn_agent"
    assert "pending" in decision.guidance


@pytest.mark.asyncio
async def test_model_decider_falls_back_when_json_is_invalid() -> None:
    decider = ModelDecider(_FakeChat("not-json"), StaticToolCatalog(), [])
    decision = await decider.decide("如何重置密码")
    assert decision.action == "answer"
    assert decision.query == "如何重置密码"


@pytest.mark.asyncio
async def test_model_decider_skill_trigger_overrides_model_answer() -> None:
    """Live coaching must not depend on the model choosing learn_agent."""
    chat = _FakeChat('{"action":"answer","query":"memory"}')
    skills = load_skills(project_root() / "skills")
    decider = ModelDecider(chat, StaticToolCatalog(), skills)
    decision = await decider.decide("教我长期记忆怎么工作")
    assert decision.action == "tool"
    assert decision.tool_name == "learn_agent"
    assert chat.calls == 0
    assert "memory.py" in decision.guidance
