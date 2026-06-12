# Phase 8 — Final Integration & Polish

**Status:** implemented
**Modules:** `tests/integration/`, `README.md`

## 8.1 End-to-end integration (`tests/integration/test_e2e.py`)

Drives the whole stack through the REST API and checks the cross-layer contracts
the frontend depends on:

- Full flow: ingest → schema → query → visualize → sandbox round-trip.
- Response keys match the TypeScript interfaces (`WarehouseSummary`,
  `DatasetSummary`, `QueryResult`, `VisualizationResult`).
- Every endpoint returns the `{ok, data, error}` envelope.
- Charts are **server-aggregated only** — the Vega-Lite spec carries inline
  aggregated `data.values`, never a full-table reference.
- **Analysis-artifact consistency:** a chart built by the agent (`ChartAction`)
  has the same mark + encoding as one built directly via `/visualize` — both go
  through the same server aggregation.
- The streamed agent `action` event carries exactly the fields the UI reads
  (`action_type`, `sql`, `spec`, `chart_request`).

## 8.2 Adversarial pass (`tests/integration/test_adversarial_full.py`)

All five priority attacks, exercised through the API:

| Attack | Defense (verified) |
|--------|--------------------|
| SQL injection via agent chat | DML "query" rejected by the SELECT-only service; canonical sha256 unchanged |
| Chart pulling a full 2.2M-row table | 12k-row scatter capped to 10,000 points, `truncated=true` |
| Sandbox escaping to the canonical DB | sandbox finds no `warehouse.duckdb` (isolated temp dir); canonical sha256 unchanged |
| Re-ingestion mutating prior data | second upload makes a new section; the first's rows are byte-identical |
| Biopack activating without opt-in | a `smiles` column stays verbatim (benzene NOT canonicalized), no `_raw` rename |

## 8.3 README

`README.md` rewritten for scientists/analysts: leads with what the app does for
the user, then install, first launch, uploading, browsing, charts, the analyst,
and sandbox experiments. CLI-first framing removed; developer details moved to a
short final section.

## Final state

146 tests passing across all layers (warehouse, ingest, services, executor,
agentic, api, integration). Eight phases complete.
