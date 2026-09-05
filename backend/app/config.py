"""Small local configuration surface. Never sent by the browser."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("AI_LAB_DATA_DIR") or ROOT / "data"))
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen3.5:9b"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5")
    )
    textbook_path: str = field(default_factory=lambda: os.getenv("TEXTBOOK_PATH", ""))
    chunk_size: int = 1400  # Characters, not tokens; keeps embedding inputs comfortably small.
    chunk_overlap: int = 200
    max_tool_rounds: int = 3
    num_ctx: int = 16384
    num_predict: int = 2048

    def find_textbook(self) -> Path | None:
        if self.textbook_path:
            path = Path(self.textbook_path).expanduser()
            return path if path.is_file() else None
        candidates = []
        for directory in (self.data_dir, ROOT, Path.home() / "Desktop" / "AIAP"):
            if directory.exists():
                candidates.extend(p for p in directory.glob("*.epub") if "ai engineering" in p.name.lower())
        # Ambiguous discoveries require TEXTBOOK_PATH, rather than silently picking a book.
        unique = sorted(set(p.resolve() for p in candidates))
        return unique[0] if len(unique) == 1 else None
