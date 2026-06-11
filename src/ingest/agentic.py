"""The agentic ingestion engine (Phase 2.2).

A local LLM (Ollama, ``qwen2.5:7b-instruct``) makes ONLY semantic decisions —
the fact grain, the identifying column, and which columns group into dimensions.
Everything else is deterministic: this module validates every proposed field
against the real data (a dimension is only accepted if its functional dependency
actually holds), assembles the tables through the shared mechanical builder, and
gates on the same five QC checks. A hallucinated proposal therefore degrades
gracefully (bad parts dropped, recorded in the audit) and can never corrupt data.

If Ollama is unavailable, the engine blocks before touching any data and never
silently falls back to deterministic.
"""

from __future__ import annotations

from datetime import datetime

from warehouse.checkpoints import quote_ident
from warehouse.naming import slugify_base
from warehouse.warehouse import Warehouse

from . import assembly
from . import biopack as biopack_mod
from .audit import IngestAudit, write_audit, write_contract
from .contract import ForeignKeySpec, StorageContract, TableSpec
from .deterministic import _infer_primary_key
from .errors import IngestRejected, ProposalError
from .ollama_client import OllamaClient
from .proposal import ModelProposal, Proposer
from .qc import run_ingest_qc
from .result import IngestResult


def build_profile(con, section: str, *, sample_rows: int = 8, sample_values: int = 6) -> dict:
    """A compact, model-friendly description of the raw table."""
    cols = assembly.raw_columns(con, section)
    n = assembly.row_count(con, section)
    stats = assembly.column_stats(con, section)
    raw = f"{quote_ident(section)}.\"raw\""
    column_profiles = []
    for c in cols:
        q = quote_ident(c)
        samples = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT {q} FROM {raw} WHERE {q} IS NOT NULL LIMIT {sample_values}"
            ).fetchall()
        ]
        column_profiles.append(
            {"name": c, "distinct": stats[c][0], "nulls": stats[c][1], "samples": samples}
        )
    rows = con.execute(f"SELECT * FROM {raw} LIMIT {sample_rows}").fetchall()
    return {
        "row_count": n,
        "columns": column_profiles,
        "sample_rows": [dict(zip(cols, r)) for r in rows],
    }


def build_contract_from_proposal(
    con,
    section: str,
    proposal: ModelProposal,
    *,
    protected_columns: frozenset[str] | set[str] = frozenset(),
) -> tuple[StorageContract, list[str], list[str]]:
    """Validate a model proposal against real data and produce a Storage Contract.

    Returns ``(contract, decisions, notes)``. ``notes`` records every place the
    model's proposal was overridden or dropped for not matching the data.
    """
    source_columns = assembly.raw_columns(con, section)
    n_rows = assembly.row_count(con, section)
    stats = assembly.column_stats(con, section)
    src = set(source_columns)
    decisions: list[str] = []
    notes: list[str] = []

    # --- primary key: accept the model's only if it is truly unique & non-null
    pk: str | None = None
    if proposal.primary_key and proposal.primary_key in src:
        distinct, nulls = stats[proposal.primary_key]
        if nulls == 0 and distinct == n_rows and n_rows > 0:
            pk = proposal.primary_key
            decisions.append(f"fact primary key (model): {pk!r}")
        else:
            notes.append(f"model PK {proposal.primary_key!r} is not unique/non-null; ignored")
    elif proposal.primary_key:
        notes.append(f"model PK {proposal.primary_key!r} is not a column; ignored")
    if pk is None:
        pk = _infer_primary_key(source_columns, stats, n_rows)
        decisions.append(f"fact primary key (derived): {pk!r}" if pk else "fact primary key: none")

    # --- dimensions: accept only those whose functional dependency truly holds
    claimed: set[str] = set()
    dim_tables: list[TableSpec] = []
    foreign_keys: list[ForeignKeySpec] = []
    used_names: set[str] = set()
    for dim in proposal.dimensions:
        k = dim.key
        if k not in src:
            notes.append(f"dimension key {k!r} is not a column; skipped")
            continue
        if k in protected_columns:
            notes.append(f"dimension key {k!r} is biopack-protected; kept in fact")
            continue
        if k == pk:
            notes.append(f"dimension key {k!r} equals the fact PK; skipped")
            continue
        if k in claimed:
            notes.append(f"dimension key {k!r} already claimed by another dimension; skipped")
            continue
        if stats[k][1] != 0:
            notes.append(f"dimension key {k!r} contains nulls; skipped")
            continue
        distinct_k = stats[k][0]
        if not (1 < distinct_k < n_rows):
            # A non-repeating key yields a degenerate 1:1 dimension; reject it,
            # matching the deterministic engine's grain rules.
            notes.append(
                f"dimension key {k!r} is not repeating (distinct={distinct_k}, rows={n_rows}); skipped"
            )
            continue
        valid_attrs: list[str] = []
        for a in dim.attributes:
            if a not in src or a == k or a == pk or a in claimed or a in protected_columns:
                notes.append(f"dimension {k!r} attribute {a!r} invalid or already claimed; dropped")
                continue
            if not assembly.functional_dependency(con, section, k, a):
                notes.append(f"dimension {k!r} does not determine {a!r} (FD fails); dropped")
                continue
            valid_attrs.append(a)
        if not valid_attrs:
            notes.append(f"dimension key {k!r} has no valid attributes; skipped")
            continue
        slug = slugify_base(dim.name or k) or "dim"
        name = f"dim_{slug}"
        i = 1
        while name in used_names:
            i += 1
            name = f"dim_{slug}_{i}"
        used_names.add(name)
        dim_tables.append(
            TableSpec(name=name, role="dimension", columns=(k, *valid_attrs), primary_key=(k,))
        )
        foreign_keys.append(
            ForeignKeySpec(table="fact", columns=(k,), ref_table=name, ref_columns=(k,))
        )
        claimed.update(valid_attrs)
        decisions.append(f"dimension {name!r} (model): key {k!r} determines {valid_attrs}")

    fact_columns = tuple(c for c in source_columns if c not in claimed)
    fact_pk = (pk,) if pk and pk in fact_columns else ()
    fact = TableSpec(name="fact", role="fact", columns=fact_columns, primary_key=fact_pk)
    contract = StorageContract(
        section=section,
        engine="agentic",
        source_columns=tuple(source_columns),
        fact_table="fact",
        tables=(fact, *dim_tables),
        foreign_keys=tuple(foreign_keys),
        grain=proposal.grain or "",
    )
    return contract, decisions, notes


class AgenticIngestor:
    """Drives a full agentic ingest. Blocks if Ollama is unavailable."""

    engine_name = "agentic"

    def __init__(self, warehouse: Warehouse, proposer: Proposer | None = None) -> None:
        self.wh = warehouse
        self.proposer = proposer or OllamaClient()

    def _model_label(self) -> str | None:
        cfg = getattr(self.proposer, "config", None)
        return getattr(cfg, "model", None)

    def ingest(
        self,
        csv_path,
        upload_timestamp: datetime,
        *,
        csv_options=None,
        biopack: dict[str, str] | None = None,
    ) -> IngestResult:
        # Block BEFORE touching data if the backend is unreachable.
        self.proposer.ensure_available()

        protected = frozenset(biopack or {})
        notes: list[str] = []
        with self.wh.staging(csv_path, upload_timestamp, csv_options=csv_options) as stg:
            profile = build_profile(stg.con, stg.section)
            try:
                proposal = self.proposer.propose(profile)
            except ProposalError as exc:
                # Reachable but unusable output: degrade to deterministic structure,
                # loudly recorded. (Availability failures propagate and block.)
                from .deterministic import analyze as deterministic_analyze

                notes.append(f"model proposal unusable ({exc}); used deterministic structure")
                contract, decisions = deterministic_analyze(
                    stg.con, stg.section, protected_columns=protected
                )
                contract = contract.model_copy(update={"engine": "agentic"})
            else:
                contract, decisions, vnotes = build_contract_from_proposal(
                    stg.con, stg.section, proposal, protected_columns=protected
                )
                notes.extend(vnotes)

            if biopack:
                contract = biopack_mod.plan(contract, biopack)
            assembly.build_relational(stg.con, stg.section, contract)
            if biopack:
                biopack_mod.apply(stg.con, stg.section, contract, biopack)
                notes.append(f"biopack applied (opt-in): {biopack}")

            report = run_ingest_qc(stg.con, stg.section, contract)
            if not report.passed:
                raise IngestRejected(report)

            stg.engine = self.engine_name
            stg.contract_json = contract.model_dump_json()
            section = stg.section
            source_filename = stg.csv_path.name
            sha256 = stg.source_hash

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
                model=self._model_label(),
                notes=tuple(notes),
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
