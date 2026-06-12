"""Generate a set of trial CSVs for exploring Locus.

Run:  python samples/generate_samples.py
Writes the CSVs into the samples/ directory (deterministic — fixed seed).
"""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path

HERE = Path(__file__).parent
random.seed(42)

# Real SMILES (some written non-canonically so biopack normalization is visible).
COMPOUNDS = [
    # name, raw_smiles, target_gene
    ("Aspirin", "CC(=O)Oc1ccccc1C(=O)O", "PTGS2"),
    ("Caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "ADORA2A"),
    ("Benzene", "C1=CC=CC=C1", "CYP2E1"),
    ("Ethanol", "OCC", "ADH1B"),  # non-canonical order
    ("Ibuprofen", "CC(C)Cc1ccc(C(C)C(=O)O)cc1", "PTGS1"),
    ("Paracetamol", "CC(=O)Nc1ccc(O)cc1", "PTGS2"),
    ("Toluene", "C1=CC=CC=C1C", "CYP2E1"),  # non-canonical
    ("Phenol", "Oc1ccccc1", "CYP2E1"),
    ("Nicotine", "CN1CCCC1c1cccnc1", "CHRNA4"),
    ("Imatinib", "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1", "ABL1"),
    ("Gefitinib", "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1", "EGFR"),
    ("Acetone", "CC(C)=O", "ADH1B"),
]

GENES = ["EGFR", "TP53", "BRCA1", "ABL1", "KRAS", "PTGS2"]
COHORTS = ["treatment_a", "treatment_b", "control"]


def write(name: str, header: list[str], rows: list[list]) -> None:
    path = HERE / name
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {name}  ({len(rows)} rows)")


def compounds_csv() -> None:
    rows = []
    for i, (cname, smiles, gene) in enumerate(COMPOUNDS, start=1):
        dose = random.choice(["10 mg", "25 mg", "5 mg/kg", "100 mg", "2.5 mg/kg"])
        mw = round(random.uniform(80, 520), 2)
        logp = round(random.uniform(-1.5, 5.5), 2)
        rows.append([f"C{i:03d}", cname, smiles, gene, dose, mw, logp])
    write(
        "compounds.csv",
        ["compound_id", "compound_name", "smiles", "target_gene", "dose", "mol_weight", "logp"],
        rows,
    )


def plate_assay_csv() -> None:
    rows = []
    letters = "ABCDEFGH"
    for plate in (1, 2):
        for ri, r in enumerate(letters):
            for c in range(1, 13):
                # a smooth gradient across the plate + a little noise
                base = 100 - (ri * 6) - (c * 3)
                readout = round(base + random.uniform(-5, 5), 1)
                cid = f"C{((ri * 12 + c) % len(COMPOUNDS)) + 1:03d}"
                rows.append([f"P{plate}", r, c, cid, readout])
    write("plate_assay.csv", ["plate_id", "well_row", "well_col", "compound_id", "readout"], rows)


def dose_response_csv() -> None:
    rows = []
    concs = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
    # each compound has its own potency (ic50) and slope
    for cname, _smiles, _gene in COMPOUNDS[:6]:
        ic50 = random.choice([0.2, 1.0, 3.0, 8.0])
        for conc in concs:
            for rep in (1, 2, 3):
                # sigmoid viability curve, higher conc -> lower viability
                v = 100 / (1 + (conc / ic50)) + random.uniform(-6, 6)
                rows.append([cname, conc, rep, round(max(0.0, v), 1)])
    write("dose_response.csv", ["compound", "concentration_uM", "replicate", "viability_pct"], rows)


def patients_csv() -> None:
    rows = []
    for i in range(1, 241):
        sex = random.choice(["F", "M"])
        cohort = random.choice(COHORTS)
        age = random.randint(21, 84)
        bmi = round(random.uniform(18.0, 38.0), 1)
        # responders depend a bit on cohort
        p_resp = {"treatment_a": 0.6, "treatment_b": 0.45, "control": 0.2}[cohort]
        responder = "yes" if random.random() < p_resp else "no"
        biomarker = round(random.uniform(0.1, 9.9) * (1.4 if responder == "yes" else 1.0), 2)
        rows.append([f"PT{i:04d}", age, sex, bmi, cohort, biomarker, responder])
    write(
        "patients.csv",
        ["patient_id", "age", "sex", "bmi", "cohort", "biomarker_level", "responder"],
        rows,
    )


def gene_expression_csv() -> None:
    rows = []
    samples = [f"S{i:03d}" for i in range(1, 21)]
    for s in samples:
        condition = "treated" if int(s[1:]) % 2 == 0 else "control"
        for gene in GENES:
            base = {"treated": 8.0, "control": 5.0}[condition]
            expr = round(base + random.gauss(0, 1.5), 3)
            rows.append([s, gene, condition, expr])
    write("gene_expression.csv", ["sample_id", "gene", "condition", "log2_expression"], rows)


def measurements_csv() -> None:
    # larger table for scatter / pagination
    rows = []
    for i in range(1, 2001):
        group = random.choice(["alpha", "beta", "gamma"])
        x = round(random.uniform(0, 100), 3)
        # y correlated with x plus group offset and noise
        offset = {"alpha": 0, "beta": 15, "gamma": -10}[group]
        y = round(1.8 * x + offset + random.gauss(0, 12), 3)
        rows.append([f"M{i:05d}", group, x, y])
    write("measurements.csv", ["measurement_id", "group", "x", "y"], rows)


def edge_cases_csv() -> None:
    # Hand-crafted to show off verbatim storage (nothing gets "cleaned").
    write(
        "edge_cases.csv",
        ["record_id", "zip_code", "decimal", "scientific", "flag", "note", "amount"],
        [
            ["1", "00123", "1.0", "1e3", "TRUE", "hello", "$1,000"],
            ["2", "007", "1.00", "1E3", "True", "a, b, c", "$2,500.00"],
            ["3", "42", "001", "2.5e-1", "false", "line with \"quotes\"", "$0.99"],
            ["4", "90210", "3.14159", "6.022E23", "FALSE", "", "$10"],
        ],
    )


if __name__ == "__main__":
    compounds_csv()
    plate_assay_csv()
    dose_response_csv()
    patients_csv()
    gene_expression_csv()
    measurements_csv()
    edge_cases_csv()
    print("\nDone. Upload any of these from the Upload tab.")
