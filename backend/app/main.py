import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .agent import SearchArguments, TutorAgent
from .config import Config
from .db import Database
from .model import OllamaRuntime, RuntimeFailure
from .retrieval import TextbookIndex

logger = logging.getLogger(__name__)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    instructions: str = Field(min_length=1, max_length=12000)
    think: bool


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)
    think: bool = False
    retry: bool = False


def create_app(config=None, runtime=None):
    config = config or Config()
    db = Database(config.data_dir / "ai_lab.sqlite3")
    runtime = runtime or OllamaRuntime(config)
    index = TextbookIndex(db, runtime, config)
    agent = TutorAgent(runtime, index, config)
    busy = set()
    index_task = None

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        yield
        if index_task and not index_task.done():
            index_task.cancel()
            await asyncio.gather(index_task, return_exceptions=True)
        await runtime.close()

    app = FastAPI(title="AI Lab — Tutor V1", lifespan=lifespan)
    app.state.db, app.state.index, app.state.agent = db, index, agent
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    allowed_origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    }
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def local_writes(request: Request, call_next):
        # Local/single-user is not permission for arbitrary websites to mutate the local app.
        if request.method in {"POST", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return await runtime.health()

    @app.get("/api/settings")
    def get_settings():
        return {"instructions": db.get("instructions"), "think": db.get("think")}

    @app.put("/api/settings")
    def save_settings(body: SettingsUpdate):
        db.set("instructions", body.instructions)
        db.set("think", body.think)
        return get_settings()

    @app.get("/api/conversations")
    def conversations():
        return db.conversations()

    @app.post("/api/conversations", status_code=201)
    def create_conversation():
        return db.create_conversation()

    def ensure_conversation(conversation_id):
        if not db.conversation(conversation_id):
            raise HTTPException(404, "Conversation not found.")

    @app.get("/api/conversations/{conversation_id}/messages")
    def messages(conversation_id: str):
        ensure_conversation(conversation_id)
        return db.messages(conversation_id)

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send(conversation_id: str, body: SendMessage):
        ensure_conversation(conversation_id)
        if conversation_id in busy:
            raise HTTPException(409, "This conversation already has a response in progress.")
        busy.add(conversation_id)
        try:
            if body.retry:
                previous = db.messages(conversation_id)
                if (
                    not previous
                    or previous[-1]["role"] != "assistant"
                    or previous[-1]["status"] not in {"error", "interrupted"}
                ):
                    raise HTTPException(409, "Only a failed or interrupted response can be retried.")
            else:
                db.add_message(conversation_id, "user", body.content, think=body.think)
            history = db.messages(conversation_id)
            assistant = db.add_message(conversation_id, "assistant", "", status="streaming", think=body.think)
            instructions = db.get("instructions")  # Fresh snapshot for every subsequent message.
        except BaseException:
            busy.discard(conversation_id)
            raise

        async def stream():
            content, sources, status, error = "", [], "interrupted", "Generation interrupted. Please retry."
            try:
                yield json.dumps({"type": "start", "message": assistant}) + "\n"
                async with asyncio.timeout(600):
                    async for event in agent.run(instructions, history, body.think):
                        if event["type"] == "reset":
                            content = ""
                        elif event["type"] == "token":
                            content += event["text"]
                        elif event["type"] == "sources":
                            sources = event["sources"]
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                status, error = "complete", None
            except (RuntimeFailure, TimeoutError, ValueError) as exc:
                status, error = "error", str(exc) or "Generation timed out. Please retry."
                yield json.dumps({"type": "error", "message": error}) + "\n"
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Tutor response failed")
                status, error = (
                    "error",
                    "An unexpected tutor error occurred. Check the backend log and retry.",
                )
                yield json.dumps({"type": "error", "message": error}) + "\n"
            finally:
                db.finish_message(assistant["id"], content, sources, status, error)
                busy.discard(conversation_id)
            yield json.dumps({"type": "done", "status": status}) + "\n"

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/graph")
    def graph():
        return db.get("graph")

    @app.get("/api/textbook/status")
    def index_status():
        return index.status()

    @app.post("/api/textbook/index", status_code=202)
    async def rebuild(force: bool = False):
        nonlocal index_task
        if index_task and not index_task.done():
            raise HTTPException(409, "Indexing is already running.")

        async def build():
            try:
                await index.rebuild(force)
            except Exception:
                logger.exception("Textbook indexing failed")

        db.set("index", {**db.get("index"), "state": "indexing", "progress": 0, "error": None})
        index_task = asyncio.create_task(build())
        return {"state": "indexing"}

    @app.post("/api/textbook/search")
    async def search(body: SearchArguments):
        try:
            return {
                "results": await index.search(
                    body.query, body.top_k, body.filters.model_dump(exclude_none=True) if body.filters else {}
                )
            }
        except (ValueError, RuntimeFailure) as exc:
            raise HTTPException(503, str(exc)) from exc

    return app


app = create_app()
