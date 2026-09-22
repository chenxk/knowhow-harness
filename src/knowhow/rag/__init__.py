"""In-process lexical retrieval. Swap the store without changing the graph."""

from knowhow.rag.ingest import ingest_dir
from knowhow.rag.store import Hit, InMemoryStore, VectorStore

__all__ = ["Hit", "InMemoryStore", "VectorStore", "ingest_dir"]
