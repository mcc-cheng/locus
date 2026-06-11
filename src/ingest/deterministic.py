"""The deterministic ingestion engine (Phase 2.1).

Input: a flat CSV (already landed verbatim as ``raw``). Output: a relational
model — a fact table plus inferred dimension tables, with inferred primary and
foreign keys — built ONLY by reorganizing the existing source columns. No value
is modified, no row is dropped, no data column is fabricated.

The heuristics below are intentionally simple and fully deterministic. Their
*quality* is a separate concern from their *correctness*: the five QC checks
(run_ingest_qc) prove the relational model round-trips to raw losslessly, so a
poor normalization is rejected rather than silently corrupting data.
"""

from __future__ import annotations

from datetime import datetime

from warehouse.naming import slugify_base
from warehouse.warehouse import Warehouse

from . import assembly
from . import biopack as biopack_mod
from .audit import IngestAudit, write_audit, write_contract
from .contract import ForeignKeySpec, StorageContract, TableSpec
from .errors import IngestRejected
from .qc import run_ingest_qc
from .result import IngestResult

# Name suffixes that mark a column as a likely key/category (dimension key).
_KEYISH_SUFFIXES = ("_id", "_code", "_key", "_no", "_type", "_category", "_class", "_group")


def _infer_primary_key(
    source_columns: list[str], stats: dict[str, tuple[int, int]], n_rows: int
) -> str | None:
    if n_rows == 0:
        return None
    candidates = [
        c for c in source_columns if stats[c][1] == 0 and stats[c][0] == n_rows
    ]  # non-null AND fully unique
    if not candidates:
        return None

    def rank(c: str) -> int:
        cl = c.lower()
        if cl == "id":
            return 0
        if cl.endswith("_id"):
            return 1
        if cl.endswith("_key"):
            return 2
        if cl.endswith("_code"):
            return 3
        return 4

    candidates.sort(key=lambda c: (rank(c), source_columns.index(c)))
    return candidates[0]


def analyze(
    con, section: str, *, protected_columns: frozenset[str] | set[str] = frozenset()
) -> tuple[StorageContract, list[str]]:
    """Derive a Storage Contract (fact + dims + keys) from the raw table.

    ``protected_columns`` (e.g. biopack-opted columns) are kept in the fact: never
    chosen as dimension keys and never absorbed as dimension attributes.
    """
    source_columns = assembly.raw_columns(con, section)
    n_rows = assembly.row_count(con, section)
    stats = assembly.column_stats(con, section)

    decisions: list[str] = []
    pk = _infer_primary_key(source_columns, stats, n_rows)
    decisions.append(f"fact primary key: {pk!r}" if pk else "fact primary key: none inferred")

    claimed: set[str] = set()  # source columns moved into a dimension
    dim_tables: list[TableSpec] = []
    foreign_keys: list[ForeignKeySpec] = []
    used_dim_names: set[str] = set()

    for k in source_columns:
        if k == pk or k in claimed or k in protected_columns:
            continue
        distinct_k, nulls_k = stats[k]
        if nulls_k != 0 or not (1 < distinct_k < n_rows):
            continue  # dim keys must be clean (non-null) and repeating
        keyish = k.lower().endswith(_KEYISH_SUFFIXES) or distinct_k <= max(1, n_rows // 2)
        if not keyish:
            continue
        deps = [
            a
            for a in source_columns
            if a != k
            and a != pk
            and a not in claimed
            and a not in protected_columns
            and assembly.functional_dependency(con, section, k, a)
        ]
        if not deps:
            continue
        slug = slugify_base(k) or "dim"
        name = f"dim_{slug}"
        i = 1
        while name in used_dim_names:
            i += 1
            name = f"dim_{slug}_{i}"
        used_dim_names.add(name)
        dim_tables.append(
            TableSpec(name=name, role="dimension", columns=(k, *deps), primary_key=(k,))
        )
        foreign_keys.append(
            ForeignKeySpec(table="fact", columns=(k,), ref_table=name, ref_columns=(k,))
        )
        claimed.update(deps)
        decisions.append(f"dimension {name!r}: key {k!r} determines {deps}")

    fact_columns = tuple(c for c in source_columns if c not in claimed)
    fact_pk = (pk,) if pk and pk in fact_columns else ()
    fact = TableSpec(name="fact", role="fact", columns=fact_columns, primary_key=fact_pk)

    contract = StorageContract(
        section=section,
        engine="deterministic",
        source_columns=tuple(source_columns),
        fact_table="fact",
        tables=(fact, *dim_tables),
        foreign_keys=tuple(foreign_keys),
    )
    return contract, decisions


class DeterministicIngestor:
    """Drives a full deterministic ingest against a warehouse."""

    engine_name = "deterministic"

    def __init__(self, warehouse: Warehouse) -> None:
        self.wh = warehouse

    def ingest(
        self,
        csv_path,
        upload_timestamp: datetime,
        *,
        csv_options=None,
        biopack: dict[str, str] | None = None,
    ) -> IngestResult:
        protected = frozenset(biopack or {})
        with self.wh.staging(csv_path, upload_timestamp, csv_options=csv_options) as stg:
            contract, decisions = analyze(stg.con, stg.section, protected_columns=protected)
            if biopack:
                contract = biopack_mod.plan(contract, biopack)
            assembly.build_relational(stg.con, stg.section, contract)
            if biopack:
                biopack_mod.apply(stg.con, stg.section, contract, biopack)
                decisions.append(f"biopack applied (opt-in): {biopack}")

            report = run_ingest_qc(stg.con, stg.section, contract)
            if not report.passed:
                raise IngestRejected(report)  # rolls back the whole section

            stg.engine = self.engine_name
            stg.contract_json = contract.model_dump_json()
            section = stg.section
            source_filename = stg.csv_path.name
            sha256 = stg.source_hash

        # Sealed and committed. Write the human-facing artifacts.
        manifest = self.wh.get_section(section)
        contract_path = self.wh.root / "contracts" / f"{section}.contract.json"
        audit_path = self.wh.root / "audit" / f"{section}.audit.json"
        write_contract(contract_path, contract)
        write_audit(
            audit_path,
            IngestAudit(
                section=section,
                engine=self.engine_name,
                source_filename=source_filename,
                sha256=sha256,
                upload_timestamp=manifest.upload_timestamp.isoformat(),
                contract=contract,
                qc_passed=report.passed,
                qc_checks=report.checks,
                decisions=tuple(decisions),
            ),
        )
        return IngestResult(
            section=section,
            manifest=manifest,
            contract=contract,
            qc=report,
            contract_path=contract_path,
            audit_path=audit_path,
        )
