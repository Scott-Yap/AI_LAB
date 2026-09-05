"""The only Ollama HTTP boundary. Tutor logic depends on its small interface."""

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from .config import Config


class RuntimeFailure(Exception):
    pass


class ModelRuntime(Protocol):
    def chat(self, messages: list[dict], tools: list[dict], think: bool) -> AsyncIterator[dict]: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaRuntime:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(base_url=config.ollama_url, timeout=httpx.Timeout(180, connect=5))

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def _error(exc: Exception, model: str) -> RuntimeFailure:
        if isinstance(exc, httpx.ConnectError):
            return RuntimeFailure("Ollama is not reachable. Start Ollama and try again.")
        if isinstance(exc, httpx.TimeoutException):
            return RuntimeFailure("Ollama timed out. The model may be loading or busy. Please retry.")
        if isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code == 404:
                return RuntimeFailure(f"Model {model} is unavailable. Run: ollama pull {model}")
            try:
                detail = exc.response.json().get("error", exc.response.text[:300])
            except ValueError:
                detail = exc.response.text[:300]
            return RuntimeFailure(f"Ollama rejected the request: {detail}")
        return RuntimeFailure(f"Ollama stream failed: {type(exc).__name__}. Please retry.")

    async def health(self):
        try:
            response = await self.client.get("/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            names = {m["name"] for m in models}
            return {
                "reachable": True,
                "model": self.config.model,
                "model_available": self.config.model in names,
                "embedding_model": self.config.embedding_model,
                "embedding_available": self.config.embedding_model in names,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "reachable": False,
                "model": self.config.model,
                "model_available": False,
                "embedding_model": self.config.embedding_model,
                "embedding_available": False,
                "error": str(self._error(exc, self.config.model)),
            }

    async def chat(self, messages, tools, think):
        # think is an actual Ollama runtime parameter, never a "think harder" prompt.
        payload = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "think": think,
            "stream": True,
            "keep_alive": "10m",
            "options": {
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
                "temperature": 0.5,
            },
        }
        try:
            async with self.client.stream("POST", "/api/chat", json=payload) as response:
                if response.is_error:
                    await response.aread()
                response.raise_for_status()
                done = False
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    part = json.loads(line)
                    if part.get("error"):
                        raise RuntimeFailure(f"Ollama: {part['error']}")
                    if part.get("message"):
                        yield part["message"]
                    if part.get("done"):
                        done = True
                        if part.get("done_reason") == "length":
                            raise RuntimeFailure(
                                "Response reached the generation limit. Try a narrower question."
                            )
                if not done:
                    raise RuntimeFailure("Ollama closed the stream before completion. Please retry.")
        except (httpx.HTTPError, ValueError) as exc:
            raise self._error(exc, self.config.model) from exc

    async def embed(self, texts):
        try:
            response = await self.client.post(
                "/api/embed",
                json={
                    "model": self.config.embedding_model,
                    "input": texts,
                    "truncate": False,
                    "keep_alive": "10m",
                },
            )
            response.raise_for_status()
            vectors = response.json()["embeddings"]
            if len(vectors) != len(texts):
                raise RuntimeFailure("Embedding model returned an unexpected number of vectors.")
            return vectors
        except (httpx.HTTPError, ValueError) as exc:
            raise self._error(exc, self.config.embedding_model) from exc
