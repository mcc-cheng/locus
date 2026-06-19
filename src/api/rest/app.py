"""Locus REST API (Phase 3.4).

FastAPI app exposing the service layer. Every endpoint returns a consistent
``{ok, data, error}`` envelope. No business logic lives here — endpoints validate
input, acquire the warehouse lock, and delegate to services/engines.

DuckDB forbids a read-write and a read-only handle on the same file in one
process, so ALL warehouse access is serialized behind a single lock and uses
short-lived per-request connections. Sandboxes use independent file copies, so
they never block ingestion.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from agentic import AnalystAgent, OllamaBrain
from agentic.mutation import MutationAction
from agentic.mutation import apply as apply_mutation
from executor import SandboxLimits, SandboxManager, SandboxRunResult, run_notebook, run_script
from ingest import (
    AgenticIngestor,
    BiopackError,
    DeterministicIngestor,
    IngestRejected,
    OllamaUnavailableError,
)
from ingest.ollama_client import OllamaClient
from services import (
    ChartRequest,
    QueryError,
    QueryService,
    SchemaService,
    ServiceError,
    VisualizationService,
)
from services import library
from warehouse import CanonicalDB, SectionNotFoundError, Warehouse
from warehouse import rows as row_ops

from .envelopes import err, ok


class QueryBody(BaseModel):
    sql: str
    page: int = 1
    page_size: int = 100
    timeout_s: float | None = None


class AgentChatBody(BaseModel):
    message: str
    history: list[dict] = []  # full conversation passed each request; no server session
    # The dataset the user is working in; scopes the agent to that one dataset.
    section: str | None = None
    # Present only when the user clicked "Confirm" on a proposed data change. The
    # exact action the agent previewed is round-tripped back and executed
    # deterministically here — the LLM is never re-run to perform the change.
    confirm: MutationAction | None = None


class RowAppendBody(BaseModel):
    values: dict[str, str | None] = {}


class CellPatchBody(BaseModel):
    column: str
    value: str | None = None


class SaveItemBody(BaseModel):
    id: str | None = None
    kind: Literal["chart", "figure"] = "chart"
    title: str | None = None
    folder: str | None = None
    section: str | None = None
    spec: dict | None = None  # charts
    chart_request: dict | None = None  # charts
    image: str | None = None  # figures (data URI)
    caption: str | None = None  # figures


class MoveItemBody(BaseModel):
    folder: str | None = None


class FolderBody(BaseModel):
    path: str


class SaveChatBody(BaseModel):
    id: str
    title: str | None = None
    section: str | None = None
    messages: list[dict] = []


class RenameChatBody(BaseModel):
    title: str


class SandboxRunBody(BaseModel):
    kind: Literal["script", "notebook"] = "script"
    code: str | None = None  # for kind="script"
    notebook: dict | None = None  # for kind="notebook"
    timeout_s: float | None = None
    cpu_seconds: int | None = None
    memory_mb: int | None = None


class AppState:
    def __init__(self, root: str | Path, brain_factory=None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # Ensure the canonical file exists so read services can open it.
        Warehouse.open(self.root).close()
        self.lock = threading.Lock()
        self.sandboxes = SandboxManager(self.root)
        self.sandbox_results: dict[str, SandboxRunResult] = {}
        # Factory for the agent's brain; overridable for tests.
        self.brain_factory = brain_factory or OllamaBrain


def create_app(root: str | Path, *, brain_factory=None) -> FastAPI:
    state = AppState(root, brain_factory=brain_factory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Warm the LLM into memory in the background so the first question is fast.
        def _warm():
            try:
                brain = state.brain_factory()
                warm = getattr(brain, "warm_up", None)
                if callable(warm):
                    warm()
            except Exception:
                pass

        threading.Thread(target=_warm, daemon=True).start()
        yield
        state.sandboxes.destroy_all()  # session end: discard all sandboxes

    app = FastAPI(title="Locus API", version="0.1.0", lifespan=lifespan)
    app.state.locus = state

    # Local desktop tool bound to 127.0.0.1; allow the dev frontend (and the
    # Tauri webview) to call it directly without cross-origin failures.
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- exception handlers: everything becomes an envelope ----
    @app.exception_handler(SectionNotFoundError)
    async def _not_found(_: Request, exc: SectionNotFoundError):
        return err(str(exc), status_code=404)

    @app.exception_handler(OllamaUnavailableError)
    async def _ollama(_: Request, exc: OllamaUnavailableError):
        return err(str(exc), status_code=503)

    @app.exception_handler(IngestRejected)
    async def _rejected(_: Request, exc: IngestRejected):
        return err(str(exc), status_code=422)

    @app.exception_handler(BiopackError)
    async def _biopack(_: Request, exc: BiopackError):
        return err(str(exc), status_code=400)

    @app.exception_handler(QueryError)
    async def _query(_: Request, exc: QueryError):
        return err(str(exc), status_code=400)

    @app.exception_handler(ServiceError)
    async def _service(_: Request, exc: ServiceError):
        return err(str(exc), status_code=400)

    # ---- health ----
    @app.get("/health")
    def health():
        return ok({"status": "ok"})

    @app.get("/health/deps")
    def health_deps():
        try:
            OllamaClient().ensure_available()
            ollama = {"status": "ready"}
        except OllamaUnavailableError as exc:
            ollama = {"status": "unavailable", "detail": str(exc)}
        return ok({"ollama": ollama})

    # ---- schema ----
    @app.get("/schema")
    def schema():
        with state.lock, SchemaService.open(state.root) as svc:
            return ok(svc.summary())

    @app.get("/schema/{section}")
    def schema_section(section: str):
        with state.lock, SchemaService.open(state.root) as svc:
            return ok(svc.get_dataset(section))

    # ---- editable rows (the data store) ---------------------------------
    @app.get("/datasets/{section}/rows")
    def read_rows(section: str, offset: int = 0, limit: int = 100):
        limit = max(1, min(limit, 1000))
        with state.lock, CanonicalDB.open(state.root) as db:
            return ok(row_ops.read_rows(db.con, section, offset=offset, limit=limit))

    @app.post("/datasets/{section}/rows")
    def add_row(section: str, body: RowAppendBody):
        with state.lock:
            wh = Warehouse.open(state.root, verify_sources=False)
            try:
                rid = row_ops.append_row(wh.con, section, body.values)
            finally:
                wh.close()
        return ok({"rid": rid}, status_code=201)

    @app.patch("/datasets/{section}/rows/{rid}")
    def patch_cell(section: str, rid: int, body: CellPatchBody):
        with state.lock:
            wh = Warehouse.open(state.root, verify_sources=False)
            try:
                row_ops.update_cell(wh.con, section, rid, body.column, body.value)
            except KeyError:
                return err(f"no column {body.column!r}", status_code=400)
            finally:
                wh.close()
        return ok({"rid": rid, "column": body.column})

    @app.delete("/datasets/{section}/rows/{rid}")
    def delete_row(section: str, rid: int):
        with state.lock:
            wh = Warehouse.open(state.root, verify_sources=False)
            try:
                deleted = row_ops.delete_row(wh.con, section, rid)
            finally:
                wh.close()
        if not deleted:
            return err(f"no row {rid}", status_code=404)
        return ok({"deleted": rid})

    @app.delete("/schema/{section}")
    def delete_dataset(section: str):
        with state.lock:
            wh = Warehouse.open(state.root)
            try:
                wh.drop_section(section)  # schema + registry + preserved source
            finally:
                wh.close()
            # Remove the ingest artifacts (contract + audit sidecars).
            for sub in ("contracts", "audit"):
                for suffix in (".contract.json", ".audit.json"):
                    p = state.root / sub / f"{section}{suffix}"
                    if p.exists():
                        p.unlink()
        return ok({"deleted": section})

    # ---- query ----
    @app.post("/query")
    def query(body: QueryBody):
        with state.lock, QueryService.open(state.root) as q:
            res = q.run(
                body.sql, page=body.page, page_size=body.page_size, timeout_s=body.timeout_s
            )
        return ok(
            {
                "columns": list(res.columns),
                "rows": res.rows,
                "page": res.page,
                "page_size": res.page_size,
                "has_more": res.has_more,
                "execution_ms": res.execution_ms,
            }
        )

    # ---- visualize ----
    @app.post("/visualize")
    def visualize(req: ChartRequest):
        with state.lock, VisualizationService.open(state.root) as viz:
            return ok(viz.visualize(req))

    @app.get("/visualize/suggestions")
    def visualize_suggestions(section: str, table: str = "raw"):
        with state.lock, VisualizationService.open(state.root) as viz:
            return ok(viz.suggest(section, table))

    # ---- ingest ----
    @app.post("/ingest")
    def ingest(
        file: UploadFile = File(...),
        engine: str = Form("deterministic"),
        biopack: str | None = Form(None),
    ):
        if engine not in ("deterministic", "agentic"):
            return err(f"unknown engine {engine!r}", status_code=400)
        biopack_cfg = _parse_biopack(biopack)
        filename = Path(file.filename or "upload.csv").name

        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / filename
            with staged.open("wb") as out:
                shutil.copyfileobj(file.file, out)

            from datetime import datetime, timezone

            ts = datetime.now(timezone.utc)
            with state.lock:
                wh = Warehouse.open(state.root)
                try:
                    ingestor = (
                        AgenticIngestor(wh)
                        if engine == "agentic"
                        else DeterministicIngestor(wh)
                    )
                    result = ingestor.ingest(staged, ts, biopack=biopack_cfg)
                finally:
                    wh.close()

        return ok(
            {
                "section": result.section,
                "engine": result.contract.engine,
                "qc_passed": result.qc.passed,
                "grain": result.contract.grain,
                "tables": [
                    {"name": t.name, "role": t.role, "columns": list(t.columns)}
                    for t in result.contract.tables
                ],
                "foreign_keys": len(result.contract.foreign_keys),
                "row_count": result.manifest.raw.row_count,
            },
            status_code=201,
        )

    # ---- sandboxes ----
    @app.post("/sandboxes")
    def create_sandbox():
        with state.lock:
            handle = state.sandboxes.create()
        return ok({"sandbox_id": handle.id}, status_code=201)

    @app.post("/sandboxes/{sandbox_id}/run")
    def run_sandbox(sandbox_id: str, body: SandboxRunBody):
        handle = state.sandboxes.get(sandbox_id)
        if handle is None:
            return err(f"no sandbox {sandbox_id!r}", status_code=404)
        overrides = {
            k: v
            for k, v in {
                "timeout_s": body.timeout_s,
                "cpu_seconds": body.cpu_seconds,
                "memory_mb": body.memory_mb,
            }.items()
            if v is not None
        }
        limits = SandboxLimits(**overrides)
        # Sandbox runs touch only the isolated clone, so they do NOT take the
        # warehouse lock — a long experiment never blocks schema/query/ingest.
        if body.kind == "script":
            if body.code is None:
                return err("a script run requires 'code'", status_code=400)
            result = run_script(handle, body.code, limits=limits)
        else:
            if body.notebook is None:
                return err("a notebook run requires 'notebook'", status_code=400)
            result = run_notebook(handle, body.notebook, limits=limits)
        state.sandbox_results[sandbox_id] = result
        return ok(result)

    @app.get("/sandboxes/{sandbox_id}/artifacts/{run_id}/{name}")
    def sandbox_artifact(sandbox_id: str, run_id: str, name: str):
        handle = state.sandboxes.get(sandbox_id)
        if handle is None:
            return err(f"no sandbox {sandbox_id!r}", status_code=404)
        # Prevent path traversal; only plain filenames within the run dir.
        if any(bad in part for part in (run_id, name) for bad in ("/", "\\", "..")):
            return err("invalid artifact path", status_code=400)
        path = handle.outputs_dir / run_id / name
        if not path.is_file():
            return err("artifact not found", status_code=404)
        return FileResponse(path)

    @app.get("/sandboxes/{sandbox_id}/results")
    def sandbox_results(sandbox_id: str):
        if state.sandboxes.get(sandbox_id) is None:
            return err(f"no sandbox {sandbox_id!r}", status_code=404)
        result = state.sandbox_results.get(sandbox_id)
        if result is None:
            return err("sandbox has no run results yet", status_code=404)
        return ok(result)

    # ---- agent chat (streaming NDJSON; no server-side session state) ----
    @app.post("/agent/chat")
    def agent_chat(body: AgentChatBody):
        def _line(obj) -> str:
            import json

            return json.dumps(jsonable_encoder(obj)) + "\n"

        def stream():
            # The agent's multi-step loop streams its own events (tool steps,
            # charts, answer tokens). We hold the warehouse lock for the turn
            # because the agent opens read-only services/clones.
            with state.lock:
                # Confirmed data change: execute the exact previewed action
                # deterministically (no LLM). This is the ONLY write path the chat
                # endpoint has, and it runs only because the user clicked Confirm.
                if body.confirm is not None:
                    for event in _apply_confirmed_mutation(state, body.confirm):
                        yield _line(event)
                    return
                agent = AnalystAgent(
                    state.root, state.brain_factory(), sandbox_manager=state.sandboxes
                )
                for event in agent.run(body.message, body.history, body.section):
                    yield _line(event)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    # ---- library: saved items (charts + figures) ------------------------
    @app.get("/library/items")
    def list_items():
        with state.lock:
            return ok(library.list_items(state.root))

    @app.post("/library/items")
    def save_item(body: SaveItemBody):
        with state.lock:
            try:
                return ok(library.save_item(state.root, body.model_dump()), status_code=201)
            except ValueError as exc:
                return err(str(exc), status_code=400)

    @app.patch("/library/items/{item_id}")
    def move_item(item_id: str, body: MoveItemBody):
        with state.lock:
            moved = library.move_item(state.root, item_id, body.folder)
            if moved is None:
                return err(f"no item {item_id!r}", status_code=404)
            return ok(moved)

    @app.delete("/library/items/{item_id}")
    def delete_item(item_id: str):
        with state.lock:
            if not library.delete_item(state.root, item_id):
                return err(f"no item {item_id!r}", status_code=404)
            return ok({"deleted": item_id})

    # ---- library: folders (a virtual tree) ------------------------------
    @app.get("/library/folders")
    def list_folders():
        with state.lock:
            return ok(library.list_folders(state.root))

    @app.post("/library/folders")
    def create_folder(body: FolderBody):
        with state.lock:
            try:
                return ok(library.create_folder(state.root, body.path), status_code=201)
            except ValueError as exc:
                return err(str(exc), status_code=400)

    @app.delete("/library/folders")
    def delete_folder(path: str):
        with state.lock:
            if not library.delete_folder(state.root, path):
                return err(f"no folder {path!r}", status_code=404)
            return ok({"deleted": path})

    # ---- library: saved chats -------------------------------------------
    @app.get("/library/chats")
    def list_chats():
        with state.lock:
            return ok(library.list_chats(state.root))

    @app.get("/library/chats/{chat_id}")
    def get_chat(chat_id: str):
        with state.lock:
            chat = library.get_chat(state.root, chat_id)
            if chat is None:
                return err(f"no chat {chat_id!r}", status_code=404)
            return ok(chat)

    @app.put("/library/chats/{chat_id}")
    def save_chat(chat_id: str, body: SaveChatBody):
        with state.lock:
            payload = body.model_dump()
            payload["id"] = chat_id
            return ok(library.save_chat(state.root, payload))

    @app.patch("/library/chats/{chat_id}")
    def rename_chat(chat_id: str, body: RenameChatBody):
        with state.lock:
            renamed = library.rename_chat(state.root, chat_id, body.title)
            if renamed is None:
                return err(f"no chat {chat_id!r}", status_code=404)
            return ok(renamed)

    @app.delete("/library/chats/{chat_id}")
    def delete_chat(chat_id: str):
        with state.lock:
            if not library.delete_chat(state.root, chat_id):
                return err(f"no chat {chat_id!r}", status_code=404)
            return ok({"deleted": chat_id})

    @app.delete("/sandboxes/{sandbox_id}")
    def delete_sandbox(sandbox_id: str):
        deleted = state.sandboxes.delete(sandbox_id)
        if not deleted:
            return err(f"no sandbox {sandbox_id!r}", status_code=404)
        state.sandbox_results.pop(sandbox_id, None)
        return ok({"deleted": sandbox_id})

    return app


def _apply_confirmed_mutation(state, action: MutationAction) -> list[dict]:
    """Execute a user-confirmed data change and return the chat events to stream
    (a ``mutation`` result the UI can act on, plus a ``final`` confirming message).
    The preserved source copy is never touched, so originals stay recoverable."""
    wh = Warehouse.open(state.root, verify_sources=False)
    try:
        result = apply_mutation(wh.con, action)
    except (ValueError, SectionNotFoundError) as exc:
        return [{"type": "error", "error": f"Could not apply the change: {exc}"}]
    except Exception as exc:  # noqa: BLE001 — surface DB errors to the user, don't crash the stream
        return [{"type": "error", "error": f"Could not apply the change: {exc}"}]
    finally:
        wh.close()
    msg = result["summary"] + " Your original uploaded file is unchanged."
    return [
        {"type": "mutation", "section": action.section, **result},
        {"type": "final", "response": msg},
    ]


def _parse_biopack(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    import json

    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QueryError(f"invalid biopack JSON: {exc}") from exc
    if not isinstance(cfg, dict):
        raise QueryError("biopack must be a JSON object of column -> transform")
    return {str(k): str(v) for k, v in cfg.items()}
