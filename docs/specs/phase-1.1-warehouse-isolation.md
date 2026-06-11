# Phase 1.1 — Warehouse Schema & Isolation

**Status:** implemented
**Module:** `src/warehouse/`

## Goal

Each uploaded CSV lands in its own isolated DuckDB **schema section**. No merging,
no cross-contamination between datasets. Every source value is stored exactly
as-is — no imputation, no type coercion, no row removal. An ingest cannot be
*sealed* until the non-regression checkpoint passes.

## Definitions

- **Warehouse** — an on-disk directory containing the canonical DuckDB file
  (`warehouse.duckdb`) and, later, the `source/` copies (Phase 1.2). One
  warehouse aggregates many datasets, each fully isolated.
- **Section** — one DuckDB schema, holding exactly one dataset's tables. Created
  from one uploaded CSV. Section schemas never reference each other.
- **Raw landing table** — `"<section>"."raw"`, the verbatim representation of the
  uploaded CSV. Every column is stored as `VARCHAR`; values are the exact text of
  the source field. No rows dropped, no values changed, no columns added.
- **`_locus` schema** — reserved internal schema holding warehouse metadata
  (the section registry). Never a user section; isolated from all user data.

## Section naming

Section name is **derived from filename + upload timestamp**, deterministically:

1. Take the filename stem (no extension), lowercase it.
2. Replace every run of non-`[a-z0-9]` characters with a single `_`.
3. Strip leading/trailing `_`. If empty, use `dataset`.
4. If it does not start with a letter, prefix `s_` (DuckDB identifier rule).
5. Truncate the base to 40 chars.
6. Append `__<YYYYMMDDTHHMMSSZ>` (UTC, from the upload timestamp).
7. If that exact name already exists in the registry, append `_2`, `_3`, … until
   unique. (Collision requires identical filename *and* same-second upload.)

Example: `Sales Data (2024).csv` uploaded at `2026-06-11T12:00:00Z`
→ `sales_data_2024__20260611T120000Z`.

## Verbatim storage rules (the non-negotiables)

- Read CSV with `all_varchar = true` — no type inference at the storage layer.
- Preserve the source field text exactly, including leading zeros, whitespace,
  scientific notation, locale formatting, mixed-case booleans.
- Preserve row count exactly. No deduplication, no row removal, no reordering of
  columns relative to the CSV header.
- Do **not** add columns to the raw table.
- `NULL` is reserved for fields the CSV genuinely omits (the configured
  `nullstr`); it is never used to "clean" a value.

## Isolation guarantees

- All of a dataset's tables live under its section schema; no object is created
  outside its section (except `_locus` metadata).
- No foreign keys or views cross section boundaries.
- Dropping a section drops only that schema; other sections are untouched.

## Non-regression checkpoint (the seal gate)

An ingest is **sealed** only if all of these pass, comparing the persisted raw
table against an independent re-read of the source CSV using identical parse
options:

1. **Row-count round-trip** — `COUNT(*)` of the stored raw table equals the data
   row count of the source CSV.
2. **Distinct-value containment** — for every column, the set of distinct stored
   values is *contained in* the set of distinct values present in the source
   (`stored ⊆ source`). This proves no value was coerced into a new form
   (`"1.0"` → `"1"`, `"TRUE"` → `true`, etc.). Equality is asserted as the
   strong form where the column maps 1:1.

If any check fails, the section is **not** sealed and the raw table is rolled
back; the caller receives a `CheckpointError` carrying the failing
`CheckResult`s. Nothing partially-ingested is left visible.

## Public contract

- `Warehouse.open(path) -> Warehouse` — open/create a warehouse directory.
- `Warehouse.land_csv(csv_path, upload_timestamp, *, csv_options=None) -> SectionManifest`
  — land a CSV into a new isolated section, run the checkpoint, and seal. Raises
  `CheckpointError` on any check failure (leaving no visible section).
- `Warehouse.list_sections() -> list[SectionManifest]`
- `Warehouse.get_section(name) -> SectionManifest`
- `Warehouse.drop_section(name)` — removes exactly one section.
- All returned objects are immutable Pydantic models (see `models.py`).
