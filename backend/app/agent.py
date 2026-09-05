"""Study this file for the explicit model -> tool -> tool-result -> model cycle."""

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .context import assemble_context, requires_textbook
from .model import RuntimeFailure


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chapter: str | None = Field(default=None, max_length=200)
    section: str | None = Field(default=None, max_length=200)


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=5)
    filters: SearchFilters | None = None


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_textbook",
        "description": "Search Chip Huyen's AI Engineering textbook. Prefer for curriculum questions; required for "
        "explicit book requests. Query in English for this English textbook. Filters are optional "
        "case-insensitive chapter/section substrings; omit them when the exact heading is unknown.",
        "parameters": SearchArguments.model_json_schema(),
    },
}


async def execute_tool(call, index):
    """All model-supplied data is validated before executing the only allowed tool."""
    function = call.get("function", {})
    if function.get("name") != "search_textbook":
        return {"ok": False, "error": "Unknown tool. Only search_textbook is available.", "results": []}
    try:
        raw = function.get("arguments", {})
        if isinstance(raw, str):
            raw = json.loads(raw)
        args = SearchArguments.model_validate(raw)
        results = await index.search(
            args.query, args.top_k, args.filters.model_dump(exclude_none=True) if args.filters else {}
        )
        return {"ok": True, "results": results}
    except (ValidationError, ValueError, RuntimeFailure) as exc:
        return {"ok": False, "error": str(exc)[:1200], "results": []}


def source_card(result):
    # Deliberately omit full passages from UI events and persisted message sources.
    return {key: result[key] for key in ("chunk_id", "title", "chapter", "section", "source_id", "score")}


class TutorAgent:
    def __init__(self, runtime, index, config):
        self.runtime, self.index, self.config = runtime, index, config

    async def run(self, instructions, history, think):
        messages = assemble_context(instructions, history)
        latest = next(m["content"] for m in reversed(history) if m["role"] == "user")
        required = requires_textbook(latest)
        grounded = False
        sources = {}
        for round_number in range(self.config.max_tool_rounds + 1):
            if len(json.dumps(messages)) > 65000:
                raise RuntimeFailure(
                    "This turn exceeded the context budget. Start a new conversation or narrow the question."
                )
            yield {"type": "status", "message": "Thinking…" if think else "Preparing response…"}
            yield {"type": "reset"}  # A tool preamble is not the final answer.
            assistant = {"role": "assistant", "content": "", "thinking": "", "tool_calls": []}
            hold_answer = required and not grounded
            async for part in self.runtime.chat(messages, [SEARCH_TOOL], think):
                assistant["thinking"] += part.get("thinking", "")  # Ephemeral; never stream or persist.
                assistant["tool_calls"].extend(part.get("tool_calls") or [])
                token = part.get("content", "")
                assistant["content"] += token
                if token and not hold_answer:
                    yield {"type": "token", "text": token}
            calls = assistant["tool_calls"]
            if not calls:
                if hold_answer:
                    if round_number == self.config.max_tool_rounds:
                        raise RuntimeFailure(
                            "The model did not retrieve the required textbook evidence. Please retry."
                        )
                    # Discard the ungrounded answer and ask Qwen itself to issue the native tool call.
                    messages.append(
                        {
                            "role": "system",
                            "content": "Retrieval is required for this request. "
                            "Call search_textbook now; do not answer before receiving its results.",
                        }
                    )
                    continue
                if not assistant["content"].strip():
                    raise RuntimeFailure("The model returned an empty answer. Please retry.")
                yield {"type": "sources", "sources": list(sources.values())}
                return
            if round_number == self.config.max_tool_rounds:
                raise RuntimeFailure(
                    "The tutor reached its textbook-search limit. Please ask a narrower question."
                )
            if len(calls) > 2:
                raise RuntimeFailure(
                    "The model requested too many tools in one turn. Please ask a narrower question."
                )
            messages.append(assistant)
            for call in calls:
                yield {"type": "status", "message": "Searching the textbook…"}
                result = await execute_tool(call, self.index)
                # The continuation receives the native assistant tool call and the tool-role result.
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.get("function", {}).get("name", "unknown"),
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                if not result["ok"]:
                    yield {"type": "warning", "message": result["error"]}
                for item in result["results"]:
                    sources[item["chunk_id"]] = source_card(item)
                grounded = grounded or bool(result["results"])
                yield {"type": "sources", "sources": list(sources.values())}
                if required and not result["ok"]:
                    raise RuntimeFailure("Cannot answer from the textbook: " + result["error"])
