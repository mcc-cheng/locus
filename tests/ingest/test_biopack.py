from __future__ import annotations

import pytest

from ingest import BIOPACK_WARNING, BiopackError, BiopackUnavailableError, DeterministicIngestor
from ingest import biopack as bp

# A compound table with a SMILES column, a gene column, and a dose column.
COMPOUNDS = (
    "compound_id,smiles,gene,dose\n"
    "C1,C1=CC=CC=C1,tp53,10 mg\n"
    "C2,CCO,brca1,2.5mg/kg\n"
    "C3,invalid_smiles,EGFR,n/a\n"
)


def _ingest(warehouse, write_csv, ts, biopack=None):
    return DeterministicIngestor(warehouse).ingest(
        write_csv("compounds.csv", COMPOUNDS), ts, biopack=biopack
    )


def test_default_is_pass_through(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts)  # no biopack
    assert res.contract.derived_columns == ()
    assert res.contract.preserved_as == {}
    # smiles column stored verbatim, untouched.
    vals = warehouse.con.execute(
        f'SELECT smiles FROM "{res.section}".fact ORDER BY compound_id'
    ).fetchall()
    assert vals[0][0] == "C1=CC=CC=C1"


def test_smiles_normalization_opt_in(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, biopack={"smiles": "smiles"})
    assert res.qc.passed  # losslessness preserved via smiles_raw
    fact_cols = set(res.contract.table("fact").columns)
    assert "smiles_raw" in fact_cols and "smiles" in fact_cols
    assert res.contract.preserved_as["smiles"] == "smiles_raw"

    rows = warehouse.con.execute(
        f'SELECT smiles_raw, smiles FROM "{res.section}".fact ORDER BY compound_id'
    ).fetchall()
    # Original preserved verbatim; canonical SMILES alongside.
    assert rows[0] == ("C1=CC=CC=C1", "c1ccccc1")  # benzene canonicalized
    assert rows[1] == ("CCO", "CCO")
    assert rows[2][0] == "invalid_smiles" and rows[2][1] is None  # bad SMILES -> NULL norm


def test_gene_parsing_opt_in(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, biopack={"gene": "gene"})
    assert res.qc.passed
    rows = warehouse.con.execute(
        f'SELECT gene_raw, gene FROM "{res.section}".fact ORDER BY compound_id'
    ).fetchall()
    assert rows[0] == ("tp53", "TP53")
    assert rows[1] == ("brca1", "BRCA1")
    assert rows[2] == ("EGFR", "EGFR")


def test_dose_parsing_opt_in(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, biopack={"dose": "dose"})
    assert res.qc.passed
    fact_cols = set(res.contract.table("fact").columns)
    assert {"dose_raw", "dose_value", "dose_unit"} <= fact_cols
    rows = warehouse.con.execute(
        f'SELECT dose_raw, dose_value, dose_unit FROM "{res.section}".fact ORDER BY compound_id'
    ).fetchall()
    assert rows[0] == ("10 mg", "10", "mg")
    assert rows[1] == ("2.5mg/kg", "2.5", "mg/kg")
    assert rows[2] == ("n/a", None, None)  # unparseable dose


def test_biopack_on_key_column_rejected(warehouse, write_csv, ts):
    # compound_id is the inferred PK; biopack must refuse to touch it.
    with pytest.raises(BiopackError):
        _ingest(warehouse, write_csv, ts, biopack={"compound_id": "gene"})
    assert warehouse.list_sections() == []


def test_blocks_when_transform_dependency_missing(warehouse, write_csv, ts, monkeypatch):
    monkeypatch.setattr(bp.TRANSFORMS["smiles"], "requires", "no_such_pkg_zzz")
    with pytest.raises(BiopackUnavailableError):
        _ingest(warehouse, write_csv, ts, biopack={"smiles": "smiles"})
    # Blocked atomically — nothing sealed.
    assert warehouse.list_sections() == []


def test_warning_text_is_exact():
    assert BIOPACK_WARNING == (
        "This will normalize SMILES strings and parse gene/dose columns. "
        "Original values will be preserved in a _raw column alongside."
    )
