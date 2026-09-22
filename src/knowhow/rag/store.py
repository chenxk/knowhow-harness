"""Lexical vector store used until a durable store is plugged in."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    text: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class VectorStore(Protocol):
    """Add and search chunks. The demo store is synchronous and in-process."""

    def add(self, chunks: list[Chunk]) -> None:
        """Index chunks. Later ids with the same `id` replace earlier ones."""

    def search(self, query: str, k: int = 4) -> list[Hit]:
        """Return up to `k` hits, highest score first."""


_WORD = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def terms(text: str) -> Counter[str]:
    """Latin words plus CJK bigrams, so short Chinese queries can match."""
    words = _WORD.findall(text.lower())
    chars = _CJK.findall(text)
    bigrams = [left + right for left, right in zip(chars, chars[1:])]
    return Counter([*words, *bigrams])


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[key] * right[key] for key in set(left) & set(right))
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm)


class InMemoryStore:
    """Bag-of-terms store. Scores are cosine similarity in `[0, 1]`."""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._terms: dict[str, Counter[str]] = {}

    def add(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
            self._terms[chunk.id] = terms(chunk.text)

    def search(self, query: str, k: int = 4) -> list[Hit]:
        query_terms = terms(query)
        ranked = [
            Hit(chunk=chunk, score=_cosine(query_terms, self._terms[chunk.id]))
            for chunk in self._chunks.values()
        ]
        ranked = [hit for hit in ranked if hit.score > 0]
        ranked.sort(key=lambda hit: hit.score, reverse=True)
        return ranked[:k]

    def __len__(self) -> int:
        return len(self._chunks)
