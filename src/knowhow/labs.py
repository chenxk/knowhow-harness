"""Checkable lab specs for learn-agent experiments."""

from __future__ import annotations

from typing import Literal, Sequence

from pydantic import BaseModel, Field

from knowhow.memory import MemoryItem

LabId = Literal["memory_promote"]
PredicateType = Literal[
    "memory_active_contains",
    "memory_pending_contains",
    "memory_any_contains",
]


class LabPredicate(BaseModel):
    """One client/server-checkable condition against live memory rows."""

    type: PredicateType
    needle: str = ""


class LabStep(BaseModel):
    """One checklist row shown in the Lab panel."""

    id: str
    label: str
    hint: str = ""
    predicate: LabPredicate


class LabSpec(BaseModel):
    """A small guided experiment wired from learn_agent topics."""

    id: LabId
    title: str
    steps: list[LabStep] = Field(default_factory=list)


_MEMORY_PROMOTE = LabSpec(
    id="memory_promote",
    title="课 1 · 长期记忆 pending→active",
    steps=[
        LabStep(
            id="explicit_active",
            label="显式「请记住」后侧栏出现 active 记忆（如绿茶）",
            hint="新开会话说：请记住：我喜欢喝绿茶",
            predicate=LabPredicate(type="memory_active_contains", needle="绿茶"),
        ),
        LabStep(
            id="implicit_pending",
            label="不说请记住时，个人事实先进 pending（如阿花）",
            hint="另开会话说：我叫阿花（不要说请记住）",
            predicate=LabPredicate(type="memory_pending_contains", needle="阿花"),
        ),
        LabStep(
            id="promote_active",
            label="重复说出或点「确认记住」后升为 active",
            hint="再说一次「我叫阿花」，或在侧栏点确认记住",
            predicate=LabPredicate(type="memory_active_contains", needle="阿花"),
        ),
    ],
)


_MEMORY_KEYS = ("记忆", "memory", "pending", "active", "请记住", "长期")
_OTHER_LESSON_KEYS = (
    "工具",
    "skill",
    "skills",
    "eval",
    "上下文",
    "context",
    "会话",
    "history",
    "观测",
    "trace",
)


def lab_for_topic(topic: str) -> LabSpec | None:
    """Return the memory lab for memory topics and generic learn overviews."""
    folded = topic.lower()
    if any(key in folded for key in _MEMORY_KEYS):
        return _MEMORY_PROMOTE.model_copy(deep=True)
    if any(key in folded for key in _OTHER_LESSON_KEYS):
        return None
    if not folded.strip() or any(
        key in folded for key in ("学习", "learn agent", "教我", "agent")
    ):
        return _MEMORY_PROMOTE.model_copy(deep=True)
    return None


def lab_by_id(lab_id: str) -> LabSpec | None:
    """Lookup a known lab by id."""
    if lab_id == "memory_promote":
        return _MEMORY_PROMOTE.model_copy(deep=True)
    return None


def check_lab_step(step: LabStep, memories: Sequence[MemoryItem]) -> bool:
    """Evaluate one lab predicate against current memory rows."""
    needle = step.predicate.needle
    kind = step.predicate.type
    if kind == "memory_active_contains":
        return any(
            item.status == "active" and needle in item.content for item in memories
        )
    if kind == "memory_pending_contains":
        return any(
            item.status == "pending" and needle in item.content for item in memories
        )
    if kind == "memory_any_contains":
        return any(needle in item.content for item in memories)
    return False


def check_lab(lab: LabSpec, memories: Sequence[MemoryItem]) -> dict[str, bool]:
    """Return pass/fail for every step id."""
    return {step.id: check_lab_step(step, memories) for step in lab.steps}
