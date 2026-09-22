"""Read a markdown directory into a `VectorStore`."""

from __future__ import annotations

import re
from pathlib import Path

from knowhow.rag.store import Chunk, VectorStore

_BLANK = re.compile(r"\n\s*\n")


def chunk_markdown(source: str, text: str, *, size: int = 500) -> list[Chunk]:
    """Split markdown on blank lines, then hard-cut oversized blocks."""
    blocks = [block.strip() for block in _BLANK.split(text) if block.strip()]
    pieces: list[str] = []
    for block in blocks:
        if len(block) <= size:
            pieces.append(block)
            continue
        for start in range(0, len(block), size):
            pieces.append(block[start : start + size])
    return [
        Chunk(id=f"{source}#{index}", source=source, text=piece)
        for index, piece in enumerate(pieces)
    ]


def ingest_dir(store: VectorStore, corpus_dir: Path) -> int:
    """Index `*.md` files. The source name is the file name, not the full path."""
    files = sorted(corpus_dir.glob("*.md"))
    chunks: list[Chunk] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        chunks.extend(chunk_markdown(path.name, text))
    store.add(chunks)
    return len(chunks)
