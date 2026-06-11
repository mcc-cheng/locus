# Phase 2.3 — Biopack Transforms (Opt-in Only)

**Status:** implemented
**Module:** `src/ingest/biopack.py`

## Goal

Biomedical normalization is **strictly opt-in**. RDKit SMILES normalization,
gene parsing, and dose parsing are NEVER applied unless the user explicitly
enables them per-upload, per-column. The default is always pass-through — values
stored verbatim.

## The exact UI warning (`BIOPACK_WARNING`)

> This will normalize SMILES strings and parse gene/dose columns. Original values
> will be preserved in a _raw column alongside.

## Transforms

| name    | dependency | output columns | preserved as |
|---------|------------|----------------|--------------|
| `smiles`| RDKit (`bio` extra) | `<col>` (canonical SMILES) | `<col>_raw` |
| `gene`  | none | `<col>` (parsed symbol, upper-cased) | `<col>_raw` |
| `dose`  | none | `<col>_value`, `<col>_unit` | `<col>_raw` |

When a column `X` is opted in, its verbatim value is preserved under `X_raw` and
the transform's outputs are added alongside as **derived columns**. Invalid input
(e.g. a malformed SMILES, an unparseable dose) yields `NULL` for the derived
column — never an error, never a guess.

## Why losslessness still holds

Derived columns are the *only* exception to "no columns added" — and only with
explicit opt-in. The non-destructive guarantee is preserved because:

- The verbatim source value is always kept (`X_raw`).
- The contract records `preserved_as[X] = "X_raw"` and marks the transform
  outputs as `derived_columns`.
- The five QC checks run against the **preserved** column: `distinct_value_
  containment` and `referential_integrity` compare `X_raw` to the source `X` and
  ignore derived columns. So a biopack ingest must *still* reconstruct raw
  exactly, or it is rejected.

## Safety rails

- Biopack may only touch plain fact columns — never the primary key, a foreign
  key, or a dimension column (`BiopackError`). Opted-in columns are also marked
  *protected* so the engines keep them in the fact (never extracted into a
  dimension).
- If a transform's dependency is missing (e.g. RDKit for `smiles`), `apply`
  raises `BiopackUnavailableError` with install instructions and the whole
  ingest is rolled back atomically — it never silently skips the normalization.

## Public contract

- `DeterministicIngestor.ingest(..., biopack={"smiles": "smiles"})`
- `AgenticIngestor.ingest(..., biopack={...})`
- `biopack.plan(contract, config) -> contract` (pure contract rewrite)
- `biopack.apply(con, section, contract, config)` (adds + computes derived cols)
- `BIOPACK_WARNING`, `TRANSFORMS`, `BiopackError`, `BiopackUnavailableError`.
