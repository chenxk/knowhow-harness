import pytest

from knowhow.config import Settings, project_root
from knowhow.runtime import build_runtime
from knowhow.skills import load_skills


def test_current_time_skill_points_at_the_clock_tool() -> None:
    skills = load_skills(project_root() / "skills")
    skill = next(item for item in skills if item.name == "current-time")
    assert skill.tool == "current_time"
    assert "几点" in skill.triggers
    assert "不要自己编造" in skill.body


@pytest.mark.asyncio
async def test_asking_the_time_calls_the_clock() -> None:
    runtime = await build_runtime(Settings(_env_file=None, mode="offline"))
    result = await runtime.run("现在几点", thread_id="clock")
    assert result.action == "tool"
    assert result.tool_name == "current_time"
    assert result.answer.startswith("当前时间：")
    assert "T" in result.answer
