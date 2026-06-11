# Phase 2.1 — Deterministic Ingestion Engine

**Status:** implemented
**Modules:** `src/ingest/{contract,assembly,deterministic,qc,audit,result}.py`

## Goal

Input: a flat CSV. Output: a relational DuckDB schema — a **fact** table plus
inferred **dimension** tables, with inferred **primary keys** and **foreign
keys** — produced *only* by reorganizing existing source columns.

**Rules (non-destructive):** no value modified, no row dropped, no data column
fabricated (no surrogate keys, no computed columns, no imputation). Keys are
chosen from existing columns; dimensions group existing columns.

## What the engine decides (deterministically)

1. **Fact primary key** — a single column that is non-null and fully unique.
   Ties broken by name priority (`id` > `*_id` > `*_key` > `*_code` > header
   order). If none, the fact has no declared PK.
2. **Dimensions** — for each clean (non-null), repeating, key-like column `K`
   (name ends in `_id/_code/_key/_no/_type/_category/_class/_group`, or low
   cardinality), the columns functionally determined by `K` are extracted into
   `dim_<K>` (one row per distinct `K`, `K` as PK). `K` stays in the fact as a
   **foreign key**. Columns are claimed at most once; processing is in header
   order, so the result is fully determined by the input.
3. **Fact table** — every source column not moved into a dimension, plus the
   dimension keys (the FKs).

`raw` (the verbatim landing) is never touched and is not part of the relational
contract; the fact/dimension tables live alongside it in the same isolated
section.

## The five QC checks (`run_ingest_qc`) — unanimous pass required

Run on seal, comparing the relational model to the verified `raw` baseline
(`raw` was already proven == source by the Phase 1.1 landing checkpoint):

1. **row_count_roundtrip** — `fact` has exactly one row per `raw` row.
2. **zero_orphan_fks** — every non-null FK value resolves to a dimension PK.
3. **distinct_value_containment** — for each source column, the distinct values
   across the relational model EQUAL those in `raw` (nothing fabricated/lost).
4. **schema_contract_match** — the physical tables/columns equal the declared
   contract (plus `raw`).
5. **referential_integrity** — `fact ⋈ dims` reconstructs `raw` EXACTLY as a
   multiset (every row, every value, every duplicate). The master guarantee.

If any check fails, `IngestRejected` is raised **inside the staging
transaction**, so the entire section is rolled back and the staged source copy
discarded. Nothing partial is ever sealed.

## Artifacts (written only after a successful seal)

- `<root>/contracts/<section>.contract.json` — the sealed Storage Contract.
- `<root>/audit/<section>.audit.json` — the audit ledger (engine, hash, contract,
  decision log, QC verdict).
- The contract JSON and engine name are also persisted in `_locus.sections`.

## Public contract

- `DeterministicIngestor(warehouse).ingest(csv_path, upload_timestamp, *, csv_options=None) -> IngestResult`
- `analyze(con, section) -> (StorageContract, decisions)` — pure decision step.
- `run_ingest_qc(con, section, contract) -> CheckpointReport`.
