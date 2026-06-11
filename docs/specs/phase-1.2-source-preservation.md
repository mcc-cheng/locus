# Phase 1.2 — Source File Preservation

**Status:** implemented
**Module:** `src/warehouse/preservation.py` (integrated into `Warehouse`)

## Goal

Every uploaded CSV is copied **byte-for-byte** to a `source/` directory alongside
the DuckDB file. The copy is made **before ingestion begins** and is **never
touched again**. Its SHA-256 is recorded at copy time and **verified on every
app launch**.

This is the ultimate backstop: even if every other layer were buggy, the user's
original bytes are recoverable and provably unaltered.

## Layout

```
<warehouse_root>/
  warehouse.duckdb
  source/
    <section_name>/
      <original_filename>      # exact byte copy, read-only
```

One subdirectory per section keeps original filenames intact and avoids
collisions between datasets that share a filename.

## Copy + hash protocol

1. Derive the section name (Phase 1.1 naming).
2. **Before any DB work**, copy the source file to
   `source/<section>/<original_filename>` using a byte-exact copy.
3. Compute the SHA-256 of the *copy* and assert it equals the SHA-256 of the
   *original* (detects copy corruption immediately).
4. Make the copy read-only (`chmod` removes write bits) so accidental in-process
   writes fail loudly.
5. Proceed with ingestion (Phase 1.1). On seal, persist the SHA-256 into the
   section registry. **On any ingestion failure, the staged source subdirectory
   is removed** — a rejected ingest leaves nothing behind, consistent with the
   Phase 1.1 rollback guarantee.

## Launch verification

`Warehouse.open(root, verify_sources=True)` (default `True`) recomputes the
SHA-256 of every recorded source file and compares it to the stored hash:

- **Missing file** → fail.
- **Hash mismatch** → fail.
- All match → pass.

If any check fails, `open()` raises `SourceIntegrityError` carrying the per-file
results, so the application refuses to start on a corrupted/tampered warehouse
rather than silently trusting it. `verify_sources=False` is available for
recovery tooling and tests only.

## Public contract

- `sha256_file(path) -> str`
- `Warehouse.land_csv(...)` copies + hashes the source before landing and stores
  the hash in the sealed section's `SectionManifest.sha256`.
- `Warehouse.source_path(section) -> Path` — the preserved copy's location.
- `Warehouse.verify_sources() -> tuple[CheckResult, ...]` — re-hash all sources.
- `Warehouse.open(root, *, verify_sources=True)` — verifies on open; raises
  `SourceIntegrityError` on any failure.
