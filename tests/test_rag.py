from knowhow.config import project_root
from knowhow.rag.ingest import ingest_dir
from knowhow.rag.store import InMemoryStore


def test_password_query_hits_password_note() -> None:
    store = InMemoryStore()
    count = ingest_dir(store, project_root() / "data" / "corpus")
    assert count >= 2
    hits = store.search("如何重置密码", k=2)
    assert hits[0].chunk.source == "password-reset.md"
    assert hits[0].score > 0.12


def test_unrelated_query_has_no_hit() -> None:
    store = InMemoryStore()
    ingest_dir(store, project_root() / "data" / "corpus")
    assert store.search("你好", k=2) == []
