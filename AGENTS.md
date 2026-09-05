# AI Lab working guide

AI Lab currently contains Tutor Agent V1 only. Read README.md and docs/architecture.md before editing.

- Backend: Python 3.12/FastAPI under backend/app. Use `.venv/bin/python`; create `.venv` with `/opt/homebrew/bin/python3.12 -m venv .venv` on this Apple Silicon Mac (arm64, not /usr/local Python).
- Frontend: React/TypeScript/Vite under frontend/src; React Flow for the curated curriculum graph.
- Generation: local Ollama `qwen3.5:9b`. Embeddings: separate `nomic-embed-text:v1.5`.
- Keep the model → native tool call → validated retrieval → tool result → model loop explicit in agent.py. No LangChain agent executor or opaque RAG chain.
- LangChain is used only for text splitting. SQLite + NumPy is the local vector store and persistence layer.
- Teaching style belongs in editable persisted Tutor Instructions. Immutable tool/grounding rules stay in context.py.
- Never expose or persist private thinking. The Think toggle must control the native Ollama `think` field.
- Preserve chapter/section/chunk metadata; only actual retrieved sources may become source cards.
- EPUB, .env, data/, virtualenv, and node_modules are private local artifacts and must not be committed.
- One backend worker. Index rebuilds must publish atomically and preserve the previous index on failure.
- Normal local lifecycle is `./start.sh` and `./stop.sh`. Ownership records contain PID, macOS process start time, and a command marker under ignored `.runtime/`; preserve validation before signaling.
- Plain `stop.sh` preserves an externally managed Ollama daemon and warm model memory; `stop.sh --unload-models` is an explicit user choice to evict the two Tutor model instances while retaining the daemon.
- Tests: `.venv/bin/pytest -q`, `.venv/bin/ruff check backend scripts`, `npm --prefix frontend test`, `npm --prefix frontend run build`.
- Live retrieval check (backend and index required): `.venv/bin/python scripts/evaluate_retrieval.py`.
- Lifecycle checks use temporary ports and a fake Ollama: `./tests/lifecycle.sh`.
- Do not add multi-agent infrastructure, learner scoring/memory, cloud services, auth, or another tutor without a new product requirement.
