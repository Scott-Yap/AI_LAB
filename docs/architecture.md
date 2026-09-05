# Tutor V1 engineering guide

## Study these ten files, in order

| File | Concepts to inspect |
| --- | --- |
| `backend/app/config.py` | Model names, runtime limits, local source discovery, chunk size/overlap |
| `backend/app/model.py` | Thin provider boundary, `/api/chat`, native Think parameter, streamed content/tool fields, `/api/embed` |
| `backend/app/context.py` | Immutable system rules, editable instruction layer, history budget, required-retrieval detection |
| `backend/app/agent.py` | Tool JSON schema, argument validation, explicit model → tool → model loop, evidence gate, source propagation |
| `backend/app/ingestion.py` | EPUB package/spine traversal, chapter filtering, heading metadata, LangChain splitting, stable chunk IDs |
| `backend/app/retrieval.py` | Document/query prefixes, batches, normalization, atomic index publication, exact cosine ranking, filters |
| `backend/app/db.py` | SQLite schema, settings seeds, conversations, message lifecycle and restart recovery |
| `backend/app/main.py` | API validation, instruction snapshot, indexing task, NDJSON events, cancellation/error persistence |
| `frontend/src/App.tsx` | Chat state, streamed updates, retry, actual retrieved source cards, thinking preference, history |
| `frontend/src/KnowledgeGraph.tsx` | React Flow nodes/edges, selection, relationship labels, concept-to-chat action |

Related files: `frontend/src/api.ts` contains the incremental NDJSON parser; `SettingsDialog.tsx` contains editable teaching instructions and index controls. `backend/app/seeds/` contains the initial instructions and curated graph. `backend/tests/retrieval_cases.json` is the generation-independent retrieval smoke benchmark.

## Important design boundaries

### Generation is the architecture owner

The first model request always includes the tool definition. The application does not prefetch textbook context for every message. If an explicit source request produces an ungrounded answer, that draft is withheld and a bounded model continuation asks for retrieval. The server never fabricates a Qwen tool call. Successful tool results carry actual chunk IDs; source cards are constructed by the application, not parsed from model prose.

### Local vectors are deliberately simple

The index keeps normalized float32 vectors in SQLite BLOBs. Search embeds the query, normalizes it, computes vector dot products, and sorts scores. At roughly a thousand chunks this is sufficient, reproducible, and readable. A vector server, reranker, or ANN index would add complexity without a demonstrated V1 need.

Ingestion works in a staging list outside the active SQLite index. After every batch succeeds, one transaction replaces chunks and active metadata. A lock and the API's single indexing task prevent overlapping rebuilds in the supported single-worker process. Failed builds retain old vectors. Model-name changes require rebuilding; replacement of a model under the same tag requires a manual forced rebuild.

### Context has bounded scope

Each turn reads current instructions and completed history. Transient tool messages are retained only within that turn; subsequent textbook claims should retrieve again. Source cards persist for learner inspection but are not injected into later context as evidence. Thinking is accumulated only for the native Ollama continuation and discarded after the turn.

The mutable teaching layer has a 12,000-character limit; user messages have a 4,000-character limit; history has a 14,000-character budget. Native generation is capped at 2,048 tokens. A coarse serialized-context guard prevents runaway tool accumulation. These character budgets approximate token budgets, so unusually token-dense text can still need shorter input.

### Streaming and durable state

The API stores the user message and a streaming assistant placeholder before generation. Events are `start`, `status`, `reset`, `token`, `sources`, `warning`, `error`, and `done`. `reset` discards a tool preamble. Sources are emitted separately from prose. The finalizer stores answer content, sources, completion/error status, and error details. The frontend recognizes truncated streams and offers retry for failed/interrupted turns without duplicating the user message.

### Source trust

Retrieved passages enter as tool data with immutable instructions to treat them as untrusted reference material. Only the allowlisted search tool can execute; it cannot read arbitrary paths or execute shell commands. CORS, Origin checks for browser writes, loopback binding, and trusted hosts protect the intended local usage. These measures do not turn the app into a network-ready authenticated service.

## External API references

Implementation follows the official [Ollama tool-calling documentation](https://docs.ollama.com/capabilities/tool-calling), [thinking parameters](https://docs.ollama.com/capabilities/thinking), and [embedding endpoint](https://docs.ollama.com/api/embed). Chunk splitting follows [LangChain's recursive text splitter](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter). The dedicated encoder is [nomic-embed-text](https://ollama.com/library/nomic-embed-text).
