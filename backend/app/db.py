"""SQLite stores user state and the single-book vector index. No server or ORM."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL, error TEXT, think INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, text TEXT NOT NULL, metadata TEXT NOT NULL, vector BLOB NOT NULL);
            """)
        seed = Path(__file__).parent / "seeds"
        self.set_default("instructions", (seed / "tutor_instructions.md").read_text())
        self.set_default("think", False)
        self.set_default("graph", json.loads((seed / "graph.json").read_text()))
        self.set_default("index", {"state": "not_indexed", "chunk_count": 0})
        # Single backend worker: recover work interrupted by a process restart.
        with self.connect() as db:
            db.execute(
                "UPDATE messages SET status='interrupted', error='Generation interrupted. Please retry.' "
                "WHERE status='streaming'"
            )
        status = self.get("index")
        if status["state"] == "indexing":
            self.set(
                "index", {**status, "state": "failed", "error": "Indexing interrupted. Rebuild to retry."}
            )

    def set_default(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def set(self, key, value):
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def create_conversation(self):
        item = {"id": str(uuid4()), "title": "New conversation", "created_at": now(), "updated_at": now()}
        with self.connect() as db:
            db.execute("INSERT INTO conversations VALUES (:id,:title,:created_at,:updated_at)", item)
        return item

    def conversations(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM conversations ORDER BY updated_at DESC")]

    def conversation(self, conversation_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            return dict(row) if row else None

    def messages(self, conversation_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,rowid", (conversation_id,)
            ).fetchall()
        return [{**dict(r), "sources": json.loads(r["sources"]), "think": bool(r["think"])} for r in rows]

    def add_message(self, conversation_id, role, content, *, status="complete", think=False):
        item = dict(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources="[]",
            status=status,
            error=None,
            think=int(think),
            created_at=now(),
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO messages VALUES (:id,:conversation_id,:role,:content,:sources,"
                ":status,:error,:think,:created_at)",
                item,
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))
            if role == "user":
                db.execute(
                    "UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                    (content[:70], conversation_id),
                )
        return {**item, "sources": [], "think": think}

    def finish_message(self, message_id, content, sources, status="complete", error=None):
        with self.connect() as db:
            db.execute(
                "UPDATE messages SET content=?,sources=?,status=?,error=? WHERE id=?",
                (content, json.dumps(sources), status, error, message_id),
            )
