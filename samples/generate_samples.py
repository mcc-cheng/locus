"""Generate a set of trial CSVs for exploring Locus.

Run:  python samples/generate_samples.py
Writes the CSVs into the samples/ directory (deterministic — fixed seed).
Every analytical dataset has 200+ rows.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

HERE = Path(__file__).parent
random.seed(42)

# Real SMILES (some written non-canonically so biopack normalization is visible).
MOLECULES = [
    ("Aspirin", "CC(=O)Oc1ccccc1C(=O)O", "PTGS2"),
    ("Caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "ADORA2A"),
    ("Benzene", "C1=CC=CC=C1", "CYP2E1"),
    ("Ethanol", "OCC", "ADH1B"),
    ("Ibuprofen", "CC(C)Cc1ccc(C(C)C(=O)O)cc1", "PTGS1"),
    ("Paracetamol", "CC(=O)Nc1ccc(O)cc1", "PTGS2"),
    ("Toluene", "C1=CC=CC=C1C", "CYP2E1"),
    ("Phenol", "Oc1ccccc1", "CYP2E1"),
    ("Nicotine", "CN1CCCC1c1cccnc1", "CHRNA4"),
    ("Imatinib", "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1", "ABL1"),
    ("Gefitinib", "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1", "EGFR"),
    ("Acetone", "CC(C)=O", "ADH1B"),
    ("Naproxen", "COc1ccc2cc(C(C)C(=O)O)ccc2c1", "PTGS1"),
    ("Diazepam", "CN1c2ccc(Cl)cc2C(c2ccccc2)=NCC1=O", "GABRA1"),
    ("Warfarin", "CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O", "VKORC1"),
    ("Metformin", "CN(C)C(=N)NC(=N)N", "PRKAA1"),
    ("Atorvastatin", "CC(C)c1c(C(=O)Nc2ccccc2)c(-c2ccccc2)c(-c2ccc(F)cc2)n1CCC(O)CC(O)CC(=O)O", "HMGCR"),
    ("Morphine", "CN1CCC23c4c5ccc(O)c4OC2C(O)C=CC3C1C5", "OPRM1"),
    ("Sucrose", "OCC1OC(OC2(CO)OC(CO)C(O)C2O)C(O)C(O)C1O", "SI"),
    ("Salicylate", "O=C(O)c1ccccc1O", "PTGS2"),
]

DOSES = ["10 mg", "25 mg", "50 mg", "100 mg", "5 mg/kg", "2.5 mg/kg", "0.5 mg/kg"]
GENES = ["EGFR", "TP53", "BRCA1", "ABL1", "KRAS", "PTGS2", "HMGCR", "VKORC1"]
COHORTS = ["treatment_a", "treatment_b", "control"]
SITES = ["Boston", "Seattle", "Austin", "Denver"]


def write(name: str, header: list[str], rows: list[list]) -> None:
    with (HERE / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {name}  ({len(rows)} rows)")


def compounds_csv() -> None:
    # Each molecule screened in several batches -> a clean compound dimension
    # plus biopack-able columns (smiles/gene/dose) in the fact.
    rows = []
    rid = 1
    for idx, (name, smiles, gene) in enumerate(MOLECULES, start=1):
        cid = f"C{idx:03d}"
        mw = round(random.uniform(80, 520), 2)
        logp = round(random.uniform(-1.5, 5.5), 2)
        for _batch in range(random.randint(10, 16)):
            rows.append(
                [
                    f"R{rid:04d}", cid, name, smiles, gene,
                    random.choice(DOSES),
                    mw, logp,
                    round(random.uniform(0, 100), 1),  # pct_inhibition
                ]
            )
            rid += 1
    write(
        "compounds.csv",
        ["assay_id", "compound_id", "compound_name", "smiles", "target_gene",
         "dose", "mol_weight", "logp", "pct_inhibition"],
        rows,
    )


def plate_assay_csv() -> None:
    rows = []
    letters = "ABCDEFGH"
    for plate in (1, 2, 3):
        for ri, r in enumerate(letters):
            for c in range(1, 13):
                base = 100 - (ri * 6) - (c * 3)
                readout = round(base + random.uniform(-5, 5), 1)
                cid = f"C{((ri * 12 + c) % len(MOLECULES)) + 1:03d}"
                rows.append([f"P{plate}", r, c, cid, readout])
    write("plate_assay.csv", ["plate_id", "well_row", "well_col", "compound_id", "readout"], rows)


def dose_response_csv() -> None:
    rows = []
    concs = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
    for name, _smiles, _gene in MOLECULES[:8]:
        ic50 = random.choice([0.2, 1.0, 3.0, 8.0, 20.0])
        for conc in concs:
            for rep in (1, 2, 3, 4):
                v = 100 / (1 + (conc / ic50)) + random.uniform(-6, 6)
                rows.append([name, conc, rep, round(max(0.0, v), 1)])
    write("dose_response.csv", ["compound", "concentration_uM", "replicate", "viability_pct"], rows)


def patients_csv() -> None:
    rows = []
    for i in range(1, 361):
        sex = random.choice(["F", "M"])
        cohort = random.choice(COHORTS)
        site = random.choice(SITES)
        age = random.randint(21, 84)
        bmi = round(random.uniform(18.0, 38.0), 1)
        p_resp = {"treatment_a": 0.62, "treatment_b": 0.45, "control": 0.2}[cohort]
        responder = "yes" if random.random() < p_resp else "no"
        biomarker = round(random.uniform(0.1, 9.9) * (1.45 if responder == "yes" else 1.0), 2)
        rows.append([f"PT{i:04d}", age, sex, bmi, cohort, site, biomarker, responder])
    write(
        "patients.csv",
        ["patient_id", "age", "sex", "bmi", "cohort", "site", "biomarker_level", "responder"],
        rows,
    )


def gene_expression_csv() -> None:
    rows = []
    samples = [f"S{i:03d}" for i in range(1, 41)]
    for s in samples:
        condition = "treated" if int(s[1:]) % 2 == 0 else "control"
        for gene in GENES:
            base = {"treated": 8.0, "control": 5.0}[condition]
            expr = round(base + random.gauss(0, 1.5), 3)
            rows.append([s, gene, condition, expr])
    write("gene_expression.csv", ["sample_id", "gene", "condition", "log2_expression"], rows)


def measurements_csv() -> None:
    rows = []
    for i in range(1, 2501):
        group = random.choice(["alpha", "beta", "gamma"])
        x = round(random.uniform(0, 100), 3)
        offset = {"alpha": 0, "beta": 15, "gamma": -10}[group]
        y = round(1.8 * x + offset + random.gauss(0, 12), 3)
        rows.append([f"M{i:05d}", group, x, y])
    write("measurements.csv", ["measurement_id", "group", "x", "y"], rows)


def edge_cases_csv() -> None:
    # 200 rows that each carry a verbatim quirk that must survive untouched.
    rows = []
    notes = ["hello", "a, b, c", 'has "quotes"', "", "trailing space ", " leading"]
    for i in range(1, 201):
        rows.append(
            [
                str(i),
                f"{i:05d}",                      # leading zeros preserved
                "1.0" if i % 2 else "1.00",       # distinct decimal text
                f"{i}e3" if i % 3 else f"{i}E3",  # scientific notation, mixed case
                random.choice(["TRUE", "True", "false", "FALSE"]),
                random.choice(notes),
                f"${i*1000:,}.00",                # currency with comma + cents
            ]
        )
    write(
        "edge_cases.csv",
        ["record_id", "zip_code", "decimal", "scientific", "flag", "note", "amount"],
        rows,
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
