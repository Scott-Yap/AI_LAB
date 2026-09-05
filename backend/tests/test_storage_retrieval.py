import json

import pytest

from app.db import Database
from app.ingestion import chunk_sections, parse_epub
from app.retrieval import TextbookIndex, unit_vectors
from conftest import FakeRuntime


def test_instructions_conversations_and_restart(db):
    db.set("instructions", "Ask me to predict.")
    conversation = db.create_conversation()
    db.add_message(conversation["id"], "user", "Teach embeddings")
    message = db.add_message(conversation["id"], "assistant", "", status="streaming", think=True)
    db.finish_message(message["id"], "What is meaning?", [{"chunk_id": "source"}])
    restarted = Database(db.path)
    restarted.initialize()
    assert restarted.get("instructions") == "Ask me to predict."
    assert restarted.conversations()[0]["title"] == "Teach embeddings"
    messages = restarted.messages(conversation["id"])
    assert len(messages) == 2 and messages[1]["sources"] == [{"chunk_id": "source"}]
    assert messages[1]["think"]


def test_restart_recovers_interrupted_work(db):
    cid = db.create_conversation()["id"]
    db.add_message(cid, "assistant", "", status="streaming")
    db.set("index", {"state": "indexing", "chunk_count": 0})
    db.initialize()
    assert db.messages(cid)[0]["status"] == "interrupted"
    assert db.get("index")["state"] == "failed"


def test_epub_chunking_metadata_and_navigation(epub):
    sections = parse_epub(epub)
    chunks = chunk_sections(sections, 400, 70)
    assert len(chunks) > 4
    assert all(len(c["text"]) <= 400 for c in chunks)
    assert all(c["metadata"]["chapter"] == "Chapter 6. RAG and Agents" for c in chunks)
    assert len({c["id"] for c in chunks}) == len(chunks)
    assert "IGNORE ME" not in str(chunks) and "NOT CONTENT" not in str(chunks)
    assert "Note" not in [s["section"] for s in sections]
    assert chunks[0]["metadata"]["anchor"] == "embedding"
    assert chunks == chunk_sections(sections, 400, 70)


async def test_index_persists_reuses_and_semantic_search(db, config, epub):
    runtime = FakeRuntime()
    index = TextbookIndex(db, runtime, config)
    await index.rebuild()
    original_calls = runtime.embedding_calls
    await index.rebuild()
    assert runtime.embedding_calls == original_calls
    restarted = TextbookIndex(Database(db.path), runtime, config)
    hits = await restarted.search("embeddings", 2)
    assert hits[0]["section"] == "Embeddings"
    assert all(
        k in hits[0] for k in ["text", "chunk_id", "chapter", "section", "title", "score", "source_id"]
    )
    filtered = await restarted.search("embeddings", 3, {"section": "Agents"})
    assert filtered and all(c["section"] == "Agents" for c in filtered)


async def test_failed_rebuild_preserves_index(db, config, epub):
    runtime = FakeRuntime()
    index = TextbookIndex(db, runtime, config)
    await index.rebuild()
    original = db.get("active_index")

    async def fail(_):
        raise ValueError("embedding unavailable")

    runtime.embed = fail
    with pytest.raises(ValueError):
        await index.rebuild(force=True)
    assert index.status()["state"] == "failed" and index.status()["searchable"]
    assert db.get("active_index") == original
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == original["chunk_count"]


async def test_missing_index_and_changed_model(db, config, epub):
    index = TextbookIndex(db, FakeRuntime(), config)
    with pytest.raises(ValueError, match="not indexed"):
        await index.search("hello")
    await index.rebuild()
    config.embedding_model = "another-model"
    with pytest.raises(ValueError, match="model changed"):
        await index.search("hello")


def test_invalid_vectors_rejected():
    for vectors in [[[0, 0]], [[float("nan"), 1]], []]:
        with pytest.raises(ValueError):
            unit_vectors(vectors)


def test_graph_validates(db):
    graph = db.get("graph")
    ids = {n["id"] for n in graph["nodes"]}
    assert len(ids) == len(graph["nodes"]) >= 15
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
    assert all(n["chapter"] and n["section"] and n["description"] for n in graph["nodes"])
    assert json.loads(json.dumps(graph)) == graph
