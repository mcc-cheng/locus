# Phase 3 — Backend Services & API

**Status:** implemented
**Modules:** `src/services/`, `src/api/rest/`, `src/executor/sandbox.py`

A clean read-only service layer plus a thin REST API. No business logic lives in
the API — endpoints validate, lock, and delegate.

## 3.1 Schema service (`services/schema_service.py`)

Read-only. `list_datasets()` / `get_dataset(section)` return `SectionManifest`s
(tables, columns + inferred types, row counts, upload timestamp, source filename,
SHA-256). `summary()` returns a `WarehouseSummary` (dataset count, total rows,
total source bytes) for the Home tab. Backed by `CanonicalDB` (read-only) and the
shared `warehouse.introspect` module. No mutations.

## 3.2 Query service (`services/query_service.py`)

- Runs against a read-only **copy-on-write clone** (canonical attached
  `READ_ONLY`, `USE canonical`).
- **SELECT-only**, enforced by DuckDB's own parser (`extract_statements` → exactly
  one `StatementType.SELECT`). DDL, DML, `PRAGMA`, `ATTACH`, `COPY`, `CALL`, and
  multi-statement inputs are all rejected.
- **Wall-clock timeout** via `con.interrupt()` from a timer thread — row limits
  don't bound compute, so a heavy aggregate over few output rows is still
  cancelled. Returns `QueryTimeoutError`.
- Paginated (`LIMIT page_size+1` to detect `has_more`); reports `execution_ms`.
- Defense in depth: even if validation were bypassed, the canonical is attached
  read-only so no write can reach it.

## 3.3 Visualization service (`services/visualization_service.py`)

Accepts a `ChartRequest`, aggregates **server-side** with DuckDB, returns a
Vega-Lite spec (inline data) + the aggregated payload. The payload is capped at
**10,000 rows** — full tables never reach the browser. Numeric roles use
`TRY_CAST(... AS DOUBLE)`; unparseable values are excluded from the *chart*, never
modified in storage. Types: `histogram`, `bar`, `heatmap` (plate/well),
`dose_response` (log-x line), `scatter`.

## 3.4 REST API (`api/rest/app.py`)

Endpoints, all returning `{ok, data, error}`:

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/ingest` | multipart CSV upload; `engine` + optional `biopack` form fields |
| GET | `/schema` | warehouse summary + datasets |
| GET | `/schema/{section}` | one dataset's structure |
| POST | `/query` | SELECT-only SQL, paginated |
| POST | `/visualize` | chart request → Vega-Lite + data |
| GET | `/health` | liveness |
| GET | `/health/deps` | Ollama readiness |
| POST | `/sandboxes` | create a sandbox (independent clone), returns `sandbox_id` |
| DELETE | `/sandboxes/{id}` | destroy a sandbox |

### Concurrency model (important)

DuckDB forbids a read-write and a read-only handle on the same file in one
process. Therefore **all warehouse access is serialized behind a single lock**
and uses short-lived per-request connections. **Sandboxes are independent file
copies** (`cow_copy_database`, APFS `clonefile` when available), so they hold no
canonical handle and never block ingestion. Run the server single-worker; this
is a single-user desktop app.

Errors map to envelopes via exception handlers: `SectionNotFoundError` → 404,
`OllamaUnavailableError` → 503, `IngestRejected` → 422, `ServiceError`/`QueryError`
/`BiopackError` → 400.
