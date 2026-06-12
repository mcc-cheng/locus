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
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from pydantic import BaseModel

from executor import SandboxManager
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
from warehouse import SectionNotFoundError, Warehouse

from .envelopes import err, ok


class QueryBody(BaseModel):
    sql: str
    page: int = 1
    page_size: int = 100
    timeout_s: float | None = None


class AppState:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # Ensure the canonical file exists so read services can open it.
        Warehouse.open(self.root).close()
        self.lock = threading.Lock()
        self.sandboxes = SandboxManager(self.root)


def create_app(root: str | Path) -> FastAPI:
    app = FastAPI(title="Locus API", version="0.1.0")
    state = AppState(root)
    app.state.locus = state

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

    @app.delete("/sandboxes/{sandbox_id}")
    def delete_sandbox(sandbox_id: str):
        deleted = state.sandboxes.delete(sandbox_id)
        if not deleted:
            return err(f"no sandbox {sandbox_id!r}", status_code=404)
        return ok({"deleted": sandbox_id})

    return app


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
