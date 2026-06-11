"""The Storage Contract (Phases 2.1 / 2.2).

A Storage Contract is the *declared* relational shape an ingestion engine
produces from a flat CSV: which tables exist, what columns each holds, the
primary keys, the foreign keys, and which table is the fact. It is the artifact
QC check #4 (schema-contract match) validates the physical DB against, and it is
serialized verbatim to ``<db>.contract.json``.

Cardinal property: the contract is a *reorganization* of the source columns.
``source_columns`` is the ground truth (the raw header, in order). Every column
named in any table must be one of ``source_columns`` — engines never invent data
columns (no surrogate keys, no computed columns, no imputation).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TableRole = Literal["fact", "dimension"]
Engine = Literal["deterministic", "agentic"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TableSpec(_Model):
    name: str
    role: TableRole
    columns: tuple[str, ...] = Field(min_length=1)
    primary_key: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _pk_subset(self) -> "TableSpec":
        missing = set(self.primary_key) - set(self.columns)
        if missing:
            raise ValueError(f"primary key columns not in table {self.name!r}: {missing}")
        return self


class ForeignKeySpec(_Model):
    table: str  # the referencing (fact) table
    columns: tuple[str, ...] = Field(min_length=1)
    ref_table: str  # the referenced (dimension) table
    ref_columns: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _arity(self) -> "ForeignKeySpec":
        if len(self.columns) != len(self.ref_columns):
            raise ValueError("foreign key column arity mismatch")
        return self


class DerivedColumnSpec(_Model):
    """A column produced by an opt-in biopack transform (Phase 2.3).

    Derived columns are the ONE exception to "no columns added" — and only ever
    when the user explicitly opts in per-upload. The verbatim source value is
    always preserved elsewhere (see ``StorageContract.preserved_as``); derived
    columns are extra and are excluded from the source-fidelity QC checks.
    """

    name: str
    table: str
    source_column: str
    transform: str


class StorageContract(_Model):
    """The sealed declaration of a section's relational shape."""

    section: str
    engine: Engine
    source_columns: tuple[str, ...] = Field(min_length=1, description="Raw header order.")
    fact_table: str
    tables: tuple[TableSpec, ...] = Field(min_length=1)
    foreign_keys: tuple[ForeignKeySpec, ...] = ()
    derived_columns: tuple[DerivedColumnSpec, ...] = ()
    preserved_as: dict[str, str] = Field(
        default_factory=dict,
        description="Maps a source column to the relational column that holds its "
        "verbatim value, when a biopack transform renamed it (e.g. smiles -> "
        "smiles_raw). Source columns absent from this map keep their own name.",
    )
    grain: str = Field(
        default="",
        description="Human-readable description of one fact row (semantic; set by "
        "the agentic engine, blank for deterministic).",
    )

    def verbatim_name(self, source_column: str) -> str:
        """The relational column holding the verbatim value of a source column."""
        return self.preserved_as.get(source_column, source_column)

    @property
    def derived_names(self) -> set[str]:
        return {d.name for d in self.derived_columns}

    @model_validator(mode="after")
    def _coherent(self) -> "StorageContract":
        names = {t.name for t in self.tables}
        if len(names) != len(self.tables):
            raise ValueError("duplicate table names in contract")
        if self.fact_table not in names:
            raise ValueError(f"fact_table {self.fact_table!r} not among tables")
        source = set(self.source_columns)
        # Allowed relational columns: each source column's verbatim representative,
        # plus any opt-in derived columns.
        allowed = {self.verbatim_name(c) for c in source} | self.derived_names
        for t in self.tables:
            extra = set(t.columns) - allowed
            if extra:
                raise ValueError(f"table {t.name!r} has unknown columns: {extra}")
        for fk in self.foreign_keys:
            if fk.table not in names or fk.ref_table not in names:
                raise ValueError(f"foreign key references unknown table: {fk}")
        for d in self.derived_columns:
            if d.source_column not in source:
                raise ValueError(f"derived {d.name!r} from unknown source {d.source_column!r}")
            if d.table not in names:
                raise ValueError(f"derived {d.name!r} on unknown table {d.table!r}")
        return self

    def table(self, name: str) -> TableSpec:
        for t in self.tables:
            if t.name == name:
                return t
        raise KeyError(name)
