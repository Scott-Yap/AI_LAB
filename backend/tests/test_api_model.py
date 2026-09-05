import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.model import OllamaRuntime, RuntimeFailure
from conftest import FakeRuntime


def test_api_settings_chat_sources_and_restart(config):
    runtime = FakeRuntime()
    with TestClient(create_app(config, runtime)) as client:
        initial = client.get("/api/settings").json()
        assert "Socratic" in initial["instructions"]
        assert (
            client.put("/api/settings", json={"instructions": "Use examples", "think": True}).status_code
            == 200
        )
        cid = client.post("/api/conversations").json()["id"]
        response = client.post(f"/api/conversations/{cid}/messages", json={"content": "Hello", "think": True})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[-1] == {"type": "done", "status": "complete"}
        assert runtime.calls[0]["think"]
        assert runtime.calls[0]["messages"][1]["content"].endswith("Use examples")
        messages = client.get(f"/api/conversations/{cid}/messages").json()
        assert len(messages) == 2 and messages[-1]["status"] == "complete"
        assert client.get("/api/graph").json()["nodes"]
        assert client.get("/api/textbook/status").json()["state"] == "not_indexed"
        assert client.post("/api/textbook/search", json={"query": "rag"}).status_code == 503
        assert client.get("/api/conversations/missing/messages").status_code == 404
        assert client.put("/api/settings", json={"instructions": " ", "think": False}).status_code == 422
        assert client.post(f"/api/conversations/{cid}/messages", json={"content": " "}).status_code == 422
        assert (
            client.post("/api/conversations", headers={"origin": "https://evil.example"}).status_code == 403
        )
    with TestClient(create_app(config, FakeRuntime())) as client:
        assert client.get("/api/settings").json()["instructions"] == "Use examples"
        assert len(client.get(f"/api/conversations/{cid}/messages").json()) == 2


def test_failed_stream_persists_and_retry_does_not_duplicate_user(config):
    runtime = FakeRuntime(
        [[{"content": "Partial"}, RuntimeFailure("Ollama disappeared")], [{"content": "Recovered"}]]
    )
    with TestClient(create_app(config, runtime)) as client:
        cid = client.post("/api/conversations").json()["id"]
        url = f"/api/conversations/{cid}/messages"
        response = client.post(url, json={"content": "Hello"})
        assert '"type": "error"' in response.text
        messages = client.get(url).json()
        assert messages[-1]["status"] == "error" and messages[-1]["content"] == "Partial"
        response = client.post(url, json={"content": "Hello", "retry": True})
        assert '"status": "complete"' in response.text
        messages = client.get(url).json()
        assert len([m for m in messages if m["role"] == "user"]) == 1
        assert messages[-1]["content"] == "Recovered"
        assert client.post(url, json={"content": "Hello", "retry": True}).status_code == 409


async def test_runtime_native_think_tool_payload_and_private_channel(config):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200, text='{"message":{"thinking":"PRIVATE"}}\n{"message":{"content":"Hi"},"done":true}\n'
        )

    runtime = OllamaRuntime(config)
    await runtime.client.aclose()
    runtime.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    for think in (True, False):
        parts = [p async for p in runtime.chat([{"role": "user", "content": "Hi"}], [], think)]
        assert parts[-1]["content"] == "Hi"
        assert payloads[-1]["think"] is think
        assert payloads[-1]["model"] == "qwen3.5:9b"
        assert payloads[-1]["stream"] is True
    await runtime.close()


@pytest.mark.parametrize(
    "status,text,match",
    [
        (404, '{"error":"missing model"}', "qwen3.5:9b is unavailable"),
        (200, '{"message":{"content":"Hi"}}\n', "before completion"),
        (200, '{"message":{},"done":true,"done_reason":"length"}\n', "generation limit"),
        (200, "not json\n", "stream failed"),
    ],
)
async def test_runtime_errors(config, status, text, match):
    runtime = OllamaRuntime(config)
    await runtime.client.aclose()
    runtime.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text=text)), base_url="http://ollama"
    )
    with pytest.raises(RuntimeFailure, match=match):
        _ = [p async for p in runtime.chat([], [], False)]
    await runtime.close()


async def test_ollama_unreachable(config):
    def fail(request):
        raise httpx.ConnectError("no server", request=request)

    runtime = OllamaRuntime(config)
    await runtime.client.aclose()
    runtime.client = httpx.AsyncClient(transport=httpx.MockTransport(fail), base_url="http://ollama")
    assert not (await runtime.health())["reachable"]
    with pytest.raises(RuntimeFailure, match="Start Ollama"):
        await runtime.embed(["hello"])
    await runtime.close()


@pytest.mark.parametrize("loaded", [[], ["qwen3.5:9b"], ["qwen3.5:9b", "nomic-embed-text:v1.5"], None])
async def test_health_distinguishes_installed_and_loaded(config, loaded):
    def reply(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": config.model},
                        {"name": config.embedding_model},
                    ]
                },
            )
        assert request.url.path == "/api/ps"
        if loaded is None:
            return httpx.Response(503)
        return httpx.Response(200, json={"models": [{"name": name} for name in loaded]})

    runtime = OllamaRuntime(config)
    await runtime.client.aclose()
    runtime.client = httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url="http://ollama")
    status = await runtime.health()
    assert status["reachable"] and status["model_available"] and status["embedding_available"]
    assert status["model_loaded"] == (config.model in loaded if loaded is not None else None)
    assert status["embedding_loaded"] == (config.embedding_model in loaded if loaded is not None else None)
    await runtime.close()
