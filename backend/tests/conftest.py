import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.config import Config
from app.db import Database


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path, textbook_path=str(tmp_path / "book.epub"))


@pytest.fixture
def db(config):
    database = Database(config.data_dir / "test.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def epub(config):
    path = Path(config.textbook_path)
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/book.opf",
            """<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>AI Engineering</dc:title></metadata><manifest><item id="ch" href="ch06.html" media-type="application/xhtml+xml"/><item id="nav" href="nav.html" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="nav"/><itemref idref="ch"/></spine></package>""",
        )
        archive.writestr("OEBPS/nav.html", "<nav>NOT CONTENT</nav>")
        archive.writestr(
            "OEBPS/ch06.html",
            '<html><body><h1>Chapter 6. RAG and Agents</h1><nav>IGNORE ME</nav><h2 id="embedding">Embeddings</h2><p>'
            + "Embeddings represent semantic meaning as vectors. " * 60
            + '</p><div data-type="note"><h6>Note</h6><p>A useful aside.</p></div><h2>Agents</h2><p>Agents call tools in a loop.</p><pre>tool(query)</pre></body></html>',
        )
    return path


class FakeRuntime:
    def __init__(self, turns=None):
        self.turns = turns or [[{"content": "Hello. What would you like to explore?"}]]
        self.calls = []
        self.embedding_calls = 0

    async def chat(self, messages, tools, think):
        self.calls.append({"messages": json.loads(json.dumps(messages)), "tools": tools, "think": think})
        turn = self.turns[min(len(self.calls) - 1, len(self.turns) - 1)]
        for part in turn:
            if isinstance(part, Exception):
                raise part
            yield part

    async def embed(self, texts):
        self.embedding_calls += 1
        return [[1.0, 0.1] if "embedding" in text.lower() else [0.1, 1.0] for text in texts]

    async def health(self):
        return {
            "reachable": True,
            "model_available": True,
            "model": "qwen3.5:9b",
            "embedding_available": True,
            "embedding_model": "nomic-embed-text:v1.5",
        }

    async def close(self):
        pass


def tool_call(name="search_textbook", arguments=None):
    return {
        "function": {"name": name, "arguments": {"query": "embeddings"} if arguments is None else arguments}
    }


class FakeIndex:
    def __init__(self, error=None, empty=False):
        self.calls = []
        self.error, self.empty = error, empty

    async def search(self, query, top_k, filters):
        self.calls.append((query, top_k, filters))
        if self.error:
            raise self.error
        return (
            []
            if self.empty
            else [
                {
                    "chunk_id": "abc",
                    "text": "Vectors capture meaning.",
                    "title": "AI Engineering",
                    "chapter": "Chapter 3",
                    "section": "Embedding",
                    "source_id": "ch03.html",
                    "score": 0.9,
                }
            ]
        )
