"""A transparent local vector store: SQLite float32 blobs + exact cosine similarity."""

import asyncio
import hashlib
import json

import numpy as np

from .db import now
from .ingestion import PARSER_VERSION, chunk_sections, parse_epub


def unit_vectors(vectors):
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] == 0 or not np.isfinite(matrix).all():
        raise ValueError("Embedding model returned invalid vectors.")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norms <= 0).any():
        raise ValueError("Embedding model returned a zero vector.")
    return matrix / norms


class TextbookIndex:
    def __init__(self, db, runtime, config):
        self.db, self.runtime, self.config = db, runtime, config
        self.lock = asyncio.Lock()

    def status(self):
        status = self.db.get("index")
        path = self.config.find_textbook()
        active = self.db.get("active_index")
        return {
            **status,
            "source_found": path is not None,
            "source_name": path.name if path else None,
            "searchable": bool(active and active["embedding_model"] == self.config.embedding_model),
            "active_index": active,
        }

    async def rebuild(self, force=False):
        async with self.lock:
            old_status = self.db.get("index")
            self.db.set("index", {**old_status, "state": "indexing", "progress": 0, "error": None})
            try:
                path = self.config.find_textbook()
                if not path:
                    raise ValueError(
                        "Textbook EPUB not found or ambiguous. Set TEXTBOOK_PATH in .env and restart."
                    )
                digest = await asyncio.to_thread(lambda: hashlib.sha256(path.read_bytes()).hexdigest())
                signature = {
                    "source_hash": digest,
                    "embedding_model": self.config.embedding_model,
                    "chunk_size": self.config.chunk_size,
                    "chunk_overlap": self.config.chunk_overlap,
                    "parser_version": PARSER_VERSION,
                }
                active = self.db.get("active_index")
                if not force and active and all(active.get(k) == v for k, v in signature.items()):
                    self.db.set(
                        "index", {"state": "ready", "progress": 100, "chunk_count": active["chunk_count"]}
                    )
                    return self.status()
                sections = await asyncio.to_thread(parse_epub, path)
                chunks = await asyncio.to_thread(
                    chunk_sections, sections, self.config.chunk_size, self.config.chunk_overlap
                )
                rows = []
                for start in range(0, len(chunks), 16):
                    batch = chunks[start : start + 16]
                    texts = [
                        f"search_document: {c['metadata']['chapter']} / {c['metadata']['section']}\n{c['text']}"
                        for c in batch
                    ]
                    vectors = unit_vectors(await self.runtime.embed(texts))
                    rows.extend(
                        (c["id"], c["text"], json.dumps(c["metadata"]), vector.tobytes())
                        for c, vector in zip(batch, vectors, strict=True)
                    )
                    self.db.set(
                        "index",
                        {
                            "state": "indexing",
                            "progress": round(len(rows) / len(chunks) * 100),
                            "chunk_count": len(chunks),
                            "error": None,
                        },
                    )
                metadata = {
                    **signature,
                    "chunk_count": len(rows),
                    "dimensions": vectors.shape[1],
                    "indexed_at": now(),
                    "title": sections[0]["title"],
                }
                # Atomic replacement: failed embeddings/rebuilds never destroy the previous usable index.
                with self.db.connect() as db:
                    db.execute("DELETE FROM chunks")
                    db.executemany("INSERT INTO chunks VALUES (?,?,?,?)", rows)
                    for key, value in (
                        ("active_index", metadata),
                        (
                            "index",
                            {"state": "ready", "progress": 100, "chunk_count": len(rows), "error": None},
                        ),
                    ):
                        db.execute(
                            "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, json.dumps(value)),
                        )
                return self.status()
            except BaseException as exc:
                self.db.set(
                    "index", {**old_status, "state": "failed", "error": str(exc) or "Indexing interrupted."}
                )
                raise

    async def search(self, query: str, top_k=4, filters=None):
        active = self.db.get("active_index")
        if not active:
            raise ValueError("Textbook is not indexed. Open Settings and choose Index textbook.")
        if active["embedding_model"] != self.config.embedding_model:
            raise ValueError("Embedding model changed. Rebuild the textbook index in Settings.")
        query_vector = unit_vectors(await self.runtime.embed([f"search_query: {query}"]))[0]
        return await asyncio.to_thread(self._similarity_search, query_vector, top_k, filters or {})

    def _similarity_search(self, query_vector, top_k, filters):
        with self.db.connect() as db:
            rows = db.execute("SELECT * FROM chunks").fetchall()
        candidates = []
        for row in rows:
            metadata = json.loads(row["metadata"])
            if any(
                value.casefold() not in metadata.get(key, "").casefold()
                for key, value in filters.items()
                if value
            ):
                continue
            vector = np.frombuffer(row["vector"], dtype=np.float32)
            if vector.shape != query_vector.shape:
                raise ValueError("Embedding dimensions changed. Rebuild the textbook index.")
            score = float(vector @ query_vector)
            candidates.append(
                {"chunk_id": row["id"], "text": row["text"], **metadata, "score": round(score, 5)}
            )
        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:top_k]
