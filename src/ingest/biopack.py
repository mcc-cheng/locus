"""Biopack transforms — strictly opt-in (Phase 2.3).

By default Locus is pure pass-through: values are stored verbatim and biopack is
NEVER applied. A user must explicitly enable a transform per-column, per-upload.
When enabled, the original value is preserved verbatim under ``<col>_raw`` and
the normalized/parsed result is added alongside as a derived column. The five QC
checks still run against the preserved ``_raw`` columns, so even with biopack on,
losslessness of the source is guaranteed.

Transforms:
  * ``smiles`` — RDKit canonical SMILES (requires the ``bio`` extra).
  * ``gene``   — gene-symbol parsing (pure Python).
  * ``dose``   — dose -> value + unit parsing (pure Python).

If a transform is requested but its dependency is missing, ``apply`` BLOCKS with
install instructions — it never silently skips.
"""

from __future__ import annotations

import re

import duckdb

from warehouse.checkpoints import quote_ident

from .contract import DerivedColumnSpec, StorageContract, TableSpec
from .errors import IngestError

# The exact warning the UI must show when biopack is enabled (Phase 6).
BIOPACK_WARNING = (
    "This will normalize SMILES strings and parse gene/dose columns. "
    "Original values will be preserved in a _raw column alongside."
)


class BiopackError(IngestError):
    """Biopack was misconfigured (e.g. applied to a key column)."""


class BiopackUnavailableError(IngestError):
    """A requested transform's dependency is not installed; the ingest blocks."""


# ---- transforms --------------------------------------------------------------


def _gene(value: str | None) -> str | None:
    if value is None:
        return None
    token = next((t for t in re.split(r"[\s,;()]+", value.strip()) if t), None)
    return token.upper() if token else None


_DOSE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-zµ%/]+(?:/[A-Za-z]+)?)?")


def _dose(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    m = _DOSE.match(value)
    if not m:
        return None, None
    return m.group(1), (m.group(2) or None)


_rdkit_canon = None


def _smiles(value: str | None) -> str | None:
    global _rdkit_canon
    if _rdkit_canon is None:
        from rdkit import Chem, RDLogger  # raises ImportError if bio extra missing

        RDLogger.DisableLog("rdApp.*")  # invalid SMILES are returned as None, not logged

        def _canon(v: str) -> str | None:
            mol = Chem.MolFromSmiles(v)
            return Chem.MolToSmiles(mol) if mol is not None else None

        _rdkit_canon = _canon
    if value is None:
        return None
    return _rdkit_canon(value)


class _Transform:
    def __init__(self, name, requires, outputs, compute):
        self.name = name
        self.requires = requires  # e.g. "rdkit" or None
        self._outputs = outputs  # (base_col) -> list[str]
        self._compute = compute  # (value) -> dict[output_name, value]

    def outputs(self, col: str) -> list[str]:
        return self._outputs(col)

    def compute(self, col: str, value: str | None) -> dict[str, str | None]:
        return self._compute(col, value)

    def ensure_available(self) -> None:
        if not self.requires:
            return
        import importlib

        try:
            importlib.import_module(self.requires)
        except ImportError as exc:
            raise BiopackUnavailableError(_UNAVAILABLE_MSG.get(self.requires, _generic_msg(self))) from exc


_UNAVAILABLE_MSG = {
    "rdkit": (
        "The 'smiles' transform needs RDKit, which is not installed.\n"
        "Install the optional biomedical extra:\n"
        "  pip install 'locus[bio]'\n"
        "Or disable biopack for this upload (values stay verbatim)."
    )
}


def _generic_msg(transform: "_Transform") -> str:
    return (
        f"The {transform.name!r} transform needs '{transform.requires}', which is "
        "not installed. Install it, or disable biopack for this upload."
    )


TRANSFORMS: dict[str, _Transform] = {
    "smiles": _Transform(
        "smiles", "rdkit", lambda c: [c], lambda c, v: {c: _smiles(v)}
    ),
    "gene": _Transform("gene", None, lambda c: [c], lambda c, v: {c: _gene(v)}),
    "dose": _Transform(
        "dose",
        None,
        lambda c: [f"{c}_value", f"{c}_unit"],
        lambda c, v: dict(zip((f"{c}_value", f"{c}_unit"), _dose(v))),
    ),
}


def _q(section: str, table: str) -> str:
    return f"{quote_ident(section)}.{quote_ident(table)}"


# ---- planning (pure contract transformation) --------------------------------


def plan(contract: StorageContract, config: dict[str, str]) -> StorageContract:
    """Rewrite a base contract to add the opt-in biopack columns.

    Each ``col -> transform`` in ``config`` renames the fact's verbatim ``col`` to
    ``col_raw`` (preserved) and declares the transform's derived output columns.
    Biopack may only touch plain fact columns — not the PK, FKs, or dimensions.
    """
    if not config:
        return contract
    fact = contract.table(contract.fact_table)
    fact_cols = set(fact.columns)
    fk_cols = {c for fk in contract.foreign_keys for c in fk.columns}

    new_fact_columns = list(fact.columns)
    preserved = dict(contract.preserved_as)
    derived: list[DerivedColumnSpec] = list(contract.derived_columns)

    for col, tname in config.items():
        if tname not in TRANSFORMS:
            raise BiopackError(f"unknown biopack transform {tname!r} for column {col!r}")
        if col not in contract.source_columns:
            raise BiopackError(f"biopack column {col!r} is not a source column")
        if col not in fact_cols:
            raise BiopackError(f"biopack column {col!r} is not a plain fact column")
        if col in fact.primary_key or col in fk_cols:
            raise BiopackError(f"biopack cannot be applied to key column {col!r}")

        raw_name = f"{col}_raw"
        preserved[col] = raw_name
        idx = new_fact_columns.index(col)
        new_fact_columns[idx] = raw_name
        for out in TRANSFORMS[tname].outputs(col):
            new_fact_columns.append(out)
            derived.append(
                DerivedColumnSpec(name=out, table=fact.name, source_column=col, transform=tname)
            )

    new_fact = TableSpec(
        name=fact.name,
        role="fact",
        columns=tuple(new_fact_columns),
        primary_key=fact.primary_key,
    )
    tables = tuple(new_fact if t.name == fact.name else t for t in contract.tables)
    return contract.model_copy(
        update={"tables": tables, "derived_columns": tuple(derived), "preserved_as": preserved}
    )


# ---- application (physical) -------------------------------------------------


def apply(
    con: duckdb.DuckDBPyConnection,
    section: str,
    contract: StorageContract,
    config: dict[str, str],
) -> None:
    """Add and compute the derived biopack columns on the already-built fact.

    Computes each transform once per DISTINCT preserved value (cheap), then joins
    the result back. Blocks if a transform's dependency is missing.
    """
    if not config:
        return
    for tname in set(config.values()):
        TRANSFORMS[tname].ensure_available()

    fact = contract.fact_table
    for col, tname in config.items():
        transform = TRANSFORMS[tname]
        raw_col = contract.verbatim_name(col)  # the preserved <col>_raw
        outputs = transform.outputs(col)

        for out in outputs:
            con.execute(f"ALTER TABLE {_q(section, fact)} ADD COLUMN {quote_ident(out)} VARCHAR")

        distinct_values = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT {quote_ident(raw_col)} FROM {_q(section, fact)}"
            ).fetchall()
        ]
        rows = []
        for v in distinct_values:
            computed = transform.compute(col, v)
            rows.append((v, *[computed.get(o) for o in outputs]))

        # Stage the mapping, update by NULL-safe join on the preserved value.
        map_cols = ", ".join(quote_ident(o) for o in outputs)
        map_decl = ", ".join(f"{quote_ident(o)} VARCHAR" for o in outputs)
        con.execute(f"CREATE TEMP TABLE _bp_map (src VARCHAR, {map_decl})")
        placeholders = ", ".join(["?"] * (1 + len(outputs)))
        con.executemany(
            f"INSERT INTO _bp_map (src, {map_cols}) VALUES ({placeholders})", rows
        )
        set_clause = ", ".join(f"{quote_ident(o)} = m.{quote_ident(o)}" for o in outputs)
        con.execute(
            f"UPDATE {_q(section, fact)} AS f SET {set_clause} "
            f"FROM _bp_map m WHERE f.{quote_ident(raw_col)} IS NOT DISTINCT FROM m.src"
        )
        con.execute("DROP TABLE _bp_map")
