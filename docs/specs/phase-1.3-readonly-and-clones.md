# Phase 1.3 — Read-only Canonical DB + Copy-on-Write Clones

**Status:** implemented
**Modules:** `src/warehouse/readonly.py`, `src/warehouse/clone.py`

## Goal

Define the read/write policy for a sealed warehouse:

- The canonical DuckDB is **always opened read-only** after ingestion seals.
- All sandbox experiments, agent queries, and visualization queries run against
  **copy-on-write clones**, never the canonical.
- Clones are **automatically discarded when the session ends**.

## The lifecycle

| Actor | Handle | Mode |
|-------|--------|------|
| Ingestion (Phase 2) | `Warehouse` | read-write (transient, privileged) |
| Schema / metadata reads (Phase 3) | `CanonicalDB` | **read-only** |
| Query / visualization / agent / sandbox (Phases 3–5) | `Clone` | read-write *clone*, canonical attached **read-only** |

Read-write access to the canonical file happens **only** during ingestion. Once
sealed, every consumer opens it read-only or works on a clone.

## `CanonicalDB` — read-only canonical

`CanonicalDB.open(root)` opens `warehouse.duckdb` with DuckDB's
`read_only=True`. The engine itself rejects any DDL/DML — a write attempt raises.
This is the cheap path for metadata and read-only `SELECT`s that never need a
writable workspace.

## `Clone` — copy-on-write workspace

A clone is a **fresh, empty, writable DuckDB database** with the canonical
**attached read-only** under the alias `canonical`:

```sql
-- inside the clone's own database file:
ATTACH '<warehouse_root>/warehouse.duckdb' AS canonical (READ_ONLY);
```

This is copy-on-write in the truest sense:

- **Reads** of canonical data (`SELECT ... FROM canonical."<section>"."raw"`) hit
  the canonical with **zero copying**.
- **Writes** (`CREATE TABLE`, `INSERT`, `UPDATE`) land in the clone's own
  database. Nothing is materialized until the experiment writes it.
- The canonical is attached `READ_ONLY`, so the engine **physically forbids**
  any write reaching it — the isolation guarantee is enforced by DuckDB, not by
  convention.

Each clone is a file under `<warehouse_root>/clones/<clone_id>.duckdb`.

## Session lifecycle & auto-discard

`CloneManager` owns all clones created during a session:

- `create() -> Clone` — make and track a new clone.
- `discard(clone)` / `discard_all()` — close the connection and delete the file.
- As a context manager, `__exit__` calls `discard_all()` — **session end discards
  every clone**. On startup, `CloneManager.for_warehouse(root)` also sweeps any
  `clones/` files orphaned by a previous crash.

## Public contract

- `CanonicalDB.open(root) -> CanonicalDB` (`.con`, `.close()`, context manager).
- `CloneManager.for_warehouse(root) -> CloneManager` (sweeps stale clones).
- `CloneManager.create() -> Clone` (`.con`, `.id`, `.path`, `.canonical_alias`).
- `Clone.close()` discards its file; `CloneManager` context exit discards all.
- Guarantee under test: no operation through a clone or `CanonicalDB` can alter
  the canonical file's bytes.
