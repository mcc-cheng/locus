# Locus

A non-destructive biomedical data aggregator.

Upload your CSVs and Locus turns them into an isolated, queryable relational
warehouse — **without ever changing a single value in your data**. Every source
file is preserved verbatim, every dataset lives in its own isolated section, and
every ingest is sealed only after a battery of non-regression checks proves that
nothing was lost or altered.

> **Status:** under active development. Phases 1–2 (data foundation + ingestion
> engine) are implemented. See [docs/specs/](docs/specs/) for the per-step
> specifications and storage guarantees.

## Core guarantees

- **Isolation** — each uploaded CSV lands in its own DuckDB schema section. No
  merging, no cross-contamination.
- **Verbatim storage** — no imputation, no type coercion, no row removal. Source
  values are stored exactly as-is.
- **Source preservation** — every uploaded file is copied byte-for-byte to a
  `source/` directory and SHA-256-verified on every launch.
- **Read-only canonical DB** — once sealed, the warehouse is opened read-only.
  All experiments run against disposable copy-on-write clones.
- **Provable ingest** — five QC checks (row-count round-trip, zero orphan FKs,
  distinct-value containment, schema-contract match, referential integrity)
  must pass unanimously or the ingest is rejected.

## Development

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
```
