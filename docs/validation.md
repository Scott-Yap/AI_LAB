# Tutor V1 validation — 2026-09-05

Environment: Apple Silicon, Python 3.12 virtual environment created with `/opt/homebrew/bin/python3.12 -m venv .venv`. `platform.machine()` confirms `arm64`. Local Ollama has `qwen3.5:9b` and `nomic-embed-text:v1.5`.

| Check | Result |
| --- | --- |
| `.venv/bin/pytest -q` | 35 passed |
| `.venv/bin/ruff check backend scripts` | Passed |
| `npm --prefix frontend test` | 5 passed |
| `npm --prefix frontend run build` | Passed; TypeScript + production Vite bundles |
| Actual EPUB ingestion | 10 chapters, 976 stored passages, ready |
| Live retrieval smoke benchmark | Expected section present in top 5 for all 6 queries |
| Real Qwen greeting, Think OFF | One model turn, zero tool calls, zero thinking-channel characters |
| Real Qwen explicit textbook question, Think ON | Tool call → retrieval → second model turn; four retrieved sources; private thinking remained separate |
| Browser concept-to-chat | Embeddings selection → Learn this concept → real streamed tutoring answer + Introduction to Embedding source card |
| Browser settings | Edited and saved instructions; persisted in SQLite and survived backend restart; original seed restored after verification |
| Persistence restart | Conversations, Think preference, and ready index survived; 976 vectors retained |
| Browser new conversation / retry | New greeting conversation and retry completed without a duplicate user message |
| Stop recovery | Interrupted message persisted; a discovered refresh race was fixed with automatic status refresh and covered by a regression test |
| Desktop visual inspection | Graph labels, selectable details, source cards, chat, settings, and welcome screen inspected |
| `./tests/lifecycle.sh` | Passed all eight lifecycle/ownership scenarios on isolated ports |
| Real `start.sh` repeated start | Reused AI Lab-owned backend/frontend; did not duplicate them |
| Real `stop.sh` with pre-existing Ollama | Stopped only AI Lab-owned backend/frontend; Ollama remained reachable |

The pytest run reports one upstream Starlette/AnyIO deprecation warning about `BlockingPortal`; it does not fail a test or affect application behavior. No functional blocker was found in these checks. Model responses are stochastic; the retrieval benchmark covers six topics and is not a comprehensive quality guarantee.

Two local smoke-test conversations are retained in history as examples. No private reasoning text is persisted or included in this report.
