import pytest

from app.agent import TutorAgent, execute_tool
from app.context import SYSTEM_INVARIANTS, assemble_context, requires_textbook
from app.model import RuntimeFailure
from conftest import FakeIndex, FakeRuntime, tool_call


def history(text):
    return [{"role": "user", "content": text, "status": "complete"}]


async def collect(agent, text="Explain embeddings"):
    return [event async for event in agent.run("Use one question at a time.", history(text), True)]


async def test_tool_then_second_model_turn(config):
    runtime = FakeRuntime(
        [[{"thinking": "PRIVATE", "tool_calls": [tool_call()]}], [{"content": "What is similar?"}]]
    )
    index = FakeIndex()
    events = await collect(TutorAgent(runtime, index, config))
    assert len(runtime.calls) == 2 and len(index.calls) == 1
    assert runtime.calls[0]["think"] is True
    assert runtime.calls[0]["tools"][0]["function"]["name"] == "search_textbook"
    assert runtime.calls[1]["messages"][-1]["role"] == "tool"
    assert runtime.calls[1]["messages"][-2]["thinking"] == "PRIVATE"
    assert "PRIVATE" not in str(events)
    assert events[-1]["sources"][0]["chunk_id"] == "abc"
    assert "text" not in events[-1]["sources"][0]


async def test_no_tool_path(config):
    runtime, index = FakeRuntime(), FakeIndex()
    events = await collect(TutorAgent(runtime, index, config), "Hello")
    assert len(runtime.calls) == 1 and not index.calls
    assert any(event["type"] == "token" for event in events)


async def test_explicit_book_answer_is_withheld_until_model_retrieves(config):
    runtime = FakeRuntime(
        [
            [{"content": "FABRICATED BOOK ANSWER"}],
            [{"tool_calls": [tool_call()]}],
            [{"content": "Grounded answer"}],
        ]
    )
    events = await collect(
        TutorAgent(runtime, FakeIndex(), config), "According to the book, what are embeddings?"
    )
    assert "FABRICATED" not in str(events)
    assert any(e.get("text") == "Grounded answer" for e in events)
    assert len(runtime.calls) == 3


async def test_explicit_book_failure_does_not_fall_back_to_claims(config):
    runtime = FakeRuntime([[{"tool_calls": [tool_call()]}], [{"content": "Unsupported"}]])
    with pytest.raises(RuntimeFailure, match="Cannot answer from the textbook"):
        await collect(
            TutorAgent(runtime, FakeIndex(error=ValueError("not indexed")), config), "Teach me this chapter"
        )
    assert len(runtime.calls) == 1


@pytest.mark.parametrize(
    "turns,text,match",
    [
        ([[{"tool_calls": [tool_call()]}]], "Hello", "search limit"),
        ([[{"content": "No tool"}]], "According to the book", "did not retrieve"),
    ],
)
async def test_loop_is_bounded(config, turns, text, match):
    runtime = FakeRuntime(turns)
    with pytest.raises(RuntimeFailure, match=match):
        await collect(TutorAgent(runtime, FakeIndex(), config), text)
    assert len(runtime.calls) == config.max_tool_rounds + 1


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": ""},
        {"query": "  "},
        {"query": "ok", "top_k": 100},
        {"query": "ok", "top_k": True},
        {"query": "ok", "filters": {"path": "/tmp"}},
        "{broken",
    ],
)
async def test_invalid_arguments_are_controlled(arguments):
    index = FakeIndex()
    result = await execute_tool(tool_call(arguments=arguments), index)
    assert not result["ok"] and not index.calls


async def test_unknown_tool_and_valid_tool():
    index = FakeIndex()
    assert not (await execute_tool(tool_call(name="shell"), index))["ok"]
    assert not index.calls
    assert (await execute_tool(tool_call(arguments='{"query":"embeddings","top_k":2}'), index))["ok"]
    assert index.calls[0] == ("embeddings", 2, {})


async def test_general_tool_error_is_returned_to_model(config):
    runtime = FakeRuntime([[{"tool_calls": [tool_call()]}], [{"content": "Search unavailable."}]])
    events = await collect(TutorAgent(runtime, FakeIndex(error=ValueError("missing index")), config))
    assert any(e["type"] == "warning" for e in events)
    assert '"ok": false' in runtime.calls[1]["messages"][-1]["content"]


def test_context_layers_and_failed_history_excluded():
    messages = assemble_context(
        "Teach with examples.",
        [*history("Hi"), {"role": "assistant", "content": "FAILED", "status": "error"}],
    )
    assert messages[0]["content"] == SYSTEM_INVARIANTS
    assert messages[1]["content"].endswith("Teach with examples.")
    assert "FAILED" not in str(messages)


@pytest.mark.parametrize(
    "text",
    ["according to the book", "what does Chip Huyen say", "teach me this chapter", "test me on this section"],
)
def test_required_retrieval_intents(text):
    assert requires_textbook(text)
