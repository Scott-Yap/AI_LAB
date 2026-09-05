"""Opt-in real-model check. Reports channel counts, never private thinking content."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agent import TutorAgent  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import Database  # noqa: E402
from app.model import OllamaRuntime  # noqa: E402
from app.retrieval import TextbookIndex  # noqa: E402


class ObservedRuntime(OllamaRuntime):
    def __init__(self, config):
        super().__init__(config)
        self.turns = []

    async def chat(self, messages, tools, think):
        counts = {"think": think, "thinking_characters": 0, "content_characters": 0, "tool_calls": 0}
        self.turns.append(counts)
        async for part in super().chat(messages, tools, think):
            counts["thinking_characters"] += len(part.get("thinking", ""))
            counts["content_characters"] += len(part.get("content", ""))
            counts["tool_calls"] += len(part.get("tool_calls") or [])
            yield part


async def main():
    config = Config()
    db = Database(config.data_dir / "ai_lab.sqlite3")
    runtime = ObservedRuntime(config)
    try:
        agent = TutorAgent(runtime, TextbookIndex(db, runtime, config), config)
        for think, question in [
            (False, "Hello!"),
            (True, "According to the book, what is semantic retrieval? Ask me one focused question."),
        ]:
            runtime.turns = []
            sources, content = [], ""
            async for event in agent.run(
                db.get("instructions"), [{"role": "user", "content": question, "status": "complete"}], think
            ):
                if event["type"] == "reset":
                    content = ""
                elif event["type"] == "token":
                    content += event["text"]
                elif event["type"] == "sources":
                    sources = event["sources"]
            assert content.strip()
            if think:
                assert sources and any(t["tool_calls"] for t in runtime.turns)
                assert any(t["thinking_characters"] for t in runtime.turns)
            else:
                assert not any(t["thinking_characters"] for t in runtime.turns)
            print(
                {
                    "think": think,
                    "model_turns": runtime.turns,
                    "source_count": len(sources),
                    "answer_characters": len(content),
                },
                flush=True,
            )
    finally:
        await runtime.close()


asyncio.run(main())
