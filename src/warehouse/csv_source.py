"""Verbatim CSV reading.

A single, shared definition of *how* a source CSV is parsed, used by both the
landing step and the non-regression checkpoint. Using one definition guarantees
the checkpoint re-reads the file exactly as it was landed.

The cardinal rule: ``all_varchar=True``. DuckDB never infers a type, so a field's
text is stored as written — no ``"1.0" -> 1``, no ``"TRUE" -> true``, no locale
mangling.
"""

from __future__ import annotations

import duckdb
from pydantic import BaseModel, ConfigDict, Field


class CsvReadOptions(BaseModel):
    """Dialect options for reading a source CSV. Frozen so a section's parse
    settings are fixed for the life of the section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    header: bool = True
    delimiter: str | None = Field(default=None, description="None => auto-detect dialect.")
    quotechar: str = '"'
    escapechar: str = '"'
    encoding: str = "utf-8"
    nullstr: tuple[str, ...] = Field(
        default=(),
        description="Tokens treated as SQL NULL. Empty => only DuckDB's notion of a "
        "missing field is NULL; explicit values are never nulled.",
    )

    def to_kwargs(self) -> dict:
        """Translate to ``DuckDBPyConnection.read_csv`` keyword arguments."""
        kwargs: dict = {
            "all_varchar": True,  # non-negotiable: no type inference
            "header": self.header,
            "quotechar": self.quotechar,
            "escapechar": self.escapechar,
            "encoding": self.encoding,
        }
        if self.delimiter is not None:
            kwargs["delimiter"] = self.delimiter
        if self.nullstr:
            # DuckDB accepts a list of null tokens via `na_values`.
            kwargs["na_values"] = list(self.nullstr)
        return kwargs


def read_source(
    con: duckdb.DuckDBPyConnection,
    csv_path: str,
    options: CsvReadOptions,
) -> duckdb.DuckDBPyRelation:
    """Return a DuckDB relation over the source CSV, parsed verbatim."""
    return con.read_csv(csv_path, **options.to_kwargs())
