# AI Lab — Tutor Agent V1

A local, single-user learning space for AI Engineering: a conversational tutor beside an interactive curriculum graph. Qwen runs through Ollama; Chip Huyen's *AI Engineering: Building Applications with Foundation Models* is the primary curriculum source. All application state and textbook vectors stay on this computer.

## Start and stop locally

Normal use from the repository root is:

```bash
cd /Users/scottyap/Desktop/AI_LAB
./start.sh
```

The launcher validates the arm64 Python 3.12 environment and frontend dependencies, reuses a healthy existing Ollama/backend/frontend, verifies both required models, starts missing AI Lab services, waits for readiness, and opens the app in the default macOS browser. Logs and ownership records live in the ignored `.runtime/` directory.

Stop only processes that the launcher owns:

```bash
cd /Users/scottyap/Desktop/AI_LAB
./stop.sh
```

If Ollama was already running, `stop.sh` leaves it running. Repeated starts and stops are safe. A port occupied by an unrelated or unhealthy service produces an error instead of killing that service.

Ollama may keep recently used models loaded for ten minutes (`ollama ps` shows an `UNTIL` time); this is warm model memory, not active generation. To explicitly evict the Tutor models while keeping an externally managed Ollama daemon running, use `./stop.sh --unload-models`. This is separate because another local application may be using the same models.

### First-time setup

On this Apple Silicon Mac, create the environment with the **arm64** Homebrew interpreter:

```bash
cd /Users/scottyap/Desktop/AI_LAB
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock.txt
npm --prefix frontend ci
```

Install missing models once (the launcher starts Ollama when needed but does not download multi-gigabyte models implicitly):

```bash
ollama pull qwen3.5:9b
ollama pull nomic-embed-text:v1.5
```

### Manual commands for debugging

Start Ollama yourself if it is not already running:

```bash
ollama serve
```

Backend, terminal 1:

```bash
cd /Users/scottyap/Desktop/AI_LAB
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Frontend, terminal 2:

```bash
cd /Users/scottyap/Desktop/AI_LAB
npm --prefix frontend run dev
```

Open [AI Lab](http://127.0.0.1:5173). API documentation: [FastAPI docs](http://127.0.0.1:8000/docs).

Use **one backend worker**. Avoid `--reload` during indexing or generation: a reload interrupts in-flight work. Both servers bind to loopback; V1 is not intended to be exposed on a network.

## Textbook setup

The app discovers a single `AI Engineering*.epub` in `data/`, the repository root, or `~/Desktop/AIAP/`. The existing textbook was found in the last location. The EPUB is read in place and is never committed or copied into frontend assets.

For another location, copy `.env.example` to `.env` and set `TEXTBOOK_PATH` to the absolute EPUB path, then restart the backend. An explicit path takes precedence; ambiguous discovery requires an explicit path.

Open **Settings → Index textbook**, or run this with the backend running:

```bash
.venv/bin/python scripts/textbook.py index
.venv/bin/python scripts/textbook.py status
.venv/bin/python scripts/textbook.py search "How does semantic retrieval work?"
```

Appearance is available in **Settings → Appearance**: System, Light, or Dark.
It applies immediately and is saved in this browser; System follows OS theme changes.
The compact **Think ON/OFF** switch beside **AI Engineering** in the chat composer
uses the existing saved Think preference. Graph spacing is presentation-only;
curriculum relationships and concept actions are unchanged.

Rebuild deliberately with **Settings → Advanced → Re-index textbook** or:

```bash
.venv/bin/python scripts/textbook.py index --force
```

Normal startup never recomputes embeddings. A non-forced index command compares a fingerprint of the source, embedding model name, parser version, chunk size, and overlap. All new vectors must succeed before an atomic SQLite transaction replaces the previous index. A failed rebuild preserves the old searchable index.

## Architecture

```text
React + TypeScript + React Flow
    │ REST / streamed NDJSON
FastAPI
    ├── SQLite: instructions, thinking preference, conversations, messages, graph, index metadata
    ├── TutorAgent: explicit bounded loop
    │      Qwen → native tool call → search_textbook → tool-role result → Qwen
    └── TextbookIndex
           EPUB → sections → chunks → Ollama embeddings → SQLite vectors → cosine search
```

- **Frontend:** React 19, TypeScript 5, Vite 7, React Flow 12, React Markdown + remark-gfm, Lucide icons. Plain CSS; no hosted fonts or external image requests. Local React state is sufficient for V1.
- **Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic validation, HTTPX, SQLite, NumPy, Beautiful Soup.
- **Generation:** `qwen3.5:9b`, configured in `backend/app/config.py` or `.env`. A thin `ModelRuntime` protocol and `OllamaRuntime` contain the runtime boundary. Native `/api/chat` uses `think: true/false`, `stream: true`, and the tool schema. Current limits are 16,384 context tokens and 2,048 generated tokens per model call.
- **Embeddings:** `nomic-embed-text:v1.5`, a small dedicated local encoder. Document and query inputs use `search_document:` and `search_query:` prefixes. Generation and embedding models are independent. Change the embedding model only with corresponding prefix review and a full rebuild.
- **Vector store:** SQLite stores normalized float32 vectors alongside chunk text and metadata. NumPy computes exact cosine similarity. A single book needs no vector server or approximate-nearest-neighbor infrastructure; linear search is easy to study.
- **LangChain:** only `RecursiveCharacterTextSplitter`, supplied by `langchain-text-splitters`. No agent executor, retriever chain, LangGraph, tracing integration, or remote service. Transitive LangChain packages are installed by its splitter dependency; this app does not invoke their services.

The dependency lock files record tested versions; `backend/requirements.txt` records intended version ranges.

## How a tutoring turn works

1. Save the user message, create an assistant placeholder, and load the latest saved Tutor Instructions.
2. Assemble immutable system invariants, a separately labeled editable instruction message, and recent completed conversation messages. History has a 14,000-character budget; failed/interrupted answers are excluded.
3. Call Qwen with the `search_textbook` JSON tool schema and the actual Think setting. General conversation can end here without retrieval.
4. Accumulate native streamed content, thinking, and tool calls. Private thinking stays in memory only for the current tool continuation; it is never sent to the UI, logged, or stored as a message.
5. Validate tool name and arguments with Pydantic. Execute semantic search, append the native assistant tool call and a structured `role: tool` result, then call Qwen again.
6. Stream answer content through NDJSON. Persist the completed answer and source metadata. Source cards contain only passages actually returned by retrieval; they mean **context retrieved**, not verified support for every generated claim.

The loop allows at most three tool rounds plus a final model turn, at most two calls per round, and at most five results per search. Unknown tools and invalid arguments become controlled tool results. Repeated tool calls terminate with an actionable error. A whole chat turn has a ten-minute timeout; Ollama read timeouts are shorter.

Curriculum retrieval is strongly encouraged in the invariant prompt and tool description. For explicit English book/author/chapter/section requests, a server-side gate withholds ungrounded content. If Qwen attempts to answer directly, the agent discards that answer and requests a tool call; it does **not** blindly retrieve before the first model call. A failed required search stops with a clear error. No successful textbook evidence means no purported textbook answer.

Tool preambles may appear briefly on ordinary turns; a reset event clears them before the final continuation. The UI displays status rather than private reasoning.

## Settings, graph, and persistence

**Tutor Settings** opens a modal with persistent editable instructions. The initial teaching instructions are the requested Socratic/active-recall workflow: Understand → Explain → Apply → Retrieve → Connect. Saving changes affects subsequent turns; an already-running turn keeps its initial snapshot. Immutable tool/source rules remain in `context.py`.

The curriculum graph is a curated seed of 19 concepts and 22 typed edges. Node records include identity, description, chapter, section, position, and a reserved status field. The seed is inserted into SQLite once. Pan, zoom, select a node, inspect relationships, search concepts, and choose **Learn this concept** to send a focused textbook-grounded prompt into the active conversation. Relations express teaching connections; they are not automatically extracted claims from the book. Status fields are placeholders, not mastery measurements.

Local state is in `data/ai_lab.sqlite3` (WAL mode). Conversations, messages, compact source cards, instructions, graph, thinking preference, vectors, and index metadata survive restarts. Back up `data/` with the backend stopped. The EPUB, `.env`, runtime state, and build artifacts are gitignored.

## Validation

```bash
.venv/bin/pytest -q
.venv/bin/ruff check backend scripts
npm --prefix frontend test
npm --prefix frontend run build
# Live retrieval benchmark; requires a running backend and indexed textbook:
.venv/bin/python scripts/evaluate_retrieval.py
# Optional real Qwen smoke test; reports channel counts without reasoning content:
.venv/bin/python scripts/smoke_ollama.py
# Isolated process-ownership and lifecycle tests on temporary ports:
./tests/lifecycle.sh
```

Automated tests mock generation at deterministic boundaries: configuration/restarts, conversations, parsing/chunk metadata, index replacement, cosine retrieval, argument validation, no-tool and tool-loop paths, mandatory retrieval, loop bounds, native thinking flags, streaming failures, API errors, and graph integrity. Frontend tests cover stream framing/truncation, instruction saving, and recovery when cancellation is persisted after the first history refresh. No assertions depend on exact Qwen prose. See [validated results](docs/validation.md).

Manual UI checks:

1. Send a greeting, then an explicit “According to the book…” question; inspect the latter's source cards.
2. Toggle Think and send a new question; answer content should appear without private reasoning.
3. Edit instructions, save, ask a follow-up, and restart to confirm persistence.
4. Select Embeddings, zoom/pan, and click Learn this concept.
5. Create/switch conversations; stop a response and retry it.
6. Inspect index readiness; rebuild progress should be visible, and a failed rebuild should preserve previous search results.

## Limitations and next milestones

V1 is one local tutor, one English EPUB, one process, and one user. It has no authentication, cloud deployment, learner memory, mastery scoring, spaced repetition, or automatic graph extraction. The explicit-intent gate recognizes common English source requests; broader paraphrases and other languages rely on the model's policy compliance. It is not a full intent classifier.

EPUB parsing preserves text and nearby headings, including textual figure captions; it does not interpret diagrams, equations as images, or page numbers. Source cards identify chapters/sections/chunks, not print pages. Similarity scores are cosine similarities, not confidence probabilities. The small hit@5 benchmark is a smoke check, not a comprehensive retrieval evaluation. Results may include overlapping passages; no reranker, hybrid retrieval, or learned relevance threshold is included.

Long conversations use recent context without summarization. Exceptionally large tool contexts stop with a budget error. Stopping a response cancels the request; completed partial content is stored when cancellation is observed, but a hard process kill may leave only an interrupted placeholder. There is no deletion/export UI or automatic backup yet. Model prose can still be wrong; retrieval does not guarantee faithful synthesis.

Deliberately deferred: additional tutors, generic agent infrastructure, remote providers, adaptive curriculum, automatic progress tracking, fine-tuning, sophisticated retrieval, and distributed serving. See [the engineering guide](docs/architecture.md) for a file-by-file study path.
