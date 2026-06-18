"""Generate CSVs each tailored to a specific statistical test.

Run:  python samples/generate_stats_datasets.py
Writes the CSVs into the samples/ directory (deterministic — fixed seed).

Every dataset has a real effect baked in (or a deliberate null, noted below) so
the matching test produces a meaningful result. Each file is named after the test
a researcher would run on it. See samples/README.md for the full table.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

HERE = Path(__file__).parent
random.seed(7)


def write(name: str, header: list[str], rows: list[list]) -> None:
    with (HERE / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {name}  ({len(rows)} rows)")


def _round(x: float, n: int = 2) -> float:
    return round(x, n)


# ---- t-tests ----------------------------------------------------------------


def ttest_independent() -> None:
    """Independent two-sample t-test: drug vs placebo on BP change.
    Drug lowers systolic BP more than placebo (real effect)."""
    rows = []
    sid = 1
    for arm, mean, sd, n in (("drug", -12.0, 7.0, 130), ("placebo", -3.0, 7.5, 130)):
        for _ in range(n):
            rows.append([f"S{sid:04d}", arm, _round(random.gauss(mean, sd), 1)])
            sid += 1
    random.shuffle(rows)
    write("ttest_independent_drug_vs_placebo.csv",
          ["subject_id", "arm", "systolic_bp_change_mmhg"], rows)


def ttest_paired() -> None:
    """Paired t-test: weight before vs after a 12-week intervention.
    Same subjects measured twice; ~3 kg mean loss."""
    rows = []
    for i in range(1, 161):
        before = _round(random.gauss(88.0, 12.0), 1)
        after = _round(before - random.gauss(3.0, 2.5), 1)
        rows.append([f"P{i:04d}", before, after])
    write("ttest_paired_weight_before_after.csv",
          ["subject_id", "weight_kg_before", "weight_kg_after"], rows)


def ttest_onesample() -> None:
    """One-sample t-test: resting heart rate vs the textbook mean of 72 bpm.
    Sample is centered slightly higher (~76)."""
    rows = []
    for i in range(1, 141):
        rows.append([f"H{i:04d}", _round(random.gauss(76.0, 8.0), 0)])
    write("ttest_onesample_resting_heart_rate.csv",
          ["subject_id", "resting_heart_rate_bpm"], rows)


# ---- ANOVA ------------------------------------------------------------------


def anova_oneway() -> None:
    """One-way ANOVA: tumor volume across four dose groups.
    Monotone decrease with dose (real effect)."""
    rows = []
    sid = 1
    groups = {"vehicle": 480.0, "low_10mg": 410.0, "mid_30mg": 330.0, "high_100mg": 240.0}
    for grp, mean in groups.items():
        for _ in range(60):
            rows.append([f"M{sid:04d}", grp, _round(random.gauss(mean, 60.0), 1)])
            sid += 1
    random.shuffle(rows)
    write("anova_oneway_dose_tumor_volume.csv",
          ["subject_id", "dose_group", "tumor_volume_mm3"], rows)


def anova_twoway() -> None:
    """Two-way ANOVA: biomarker response by drug (A/B) and sex (M/F),
    with a drug-by-sex interaction baked in."""
    rows = []
    sid = 1
    # base effects + interaction (drug B works better in females)
    cell = {
        ("A", "M"): 50.0, ("A", "F"): 52.0,
        ("B", "M"): 55.0, ("B", "F"): 68.0,
    }
    for drug in ("A", "B"):
        for sex in ("M", "F"):
            for _ in range(55):
                rows.append([f"X{sid:04d}", drug, sex,
                             _round(random.gauss(cell[(drug, sex)], 9.0), 1)])
                sid += 1
    random.shuffle(rows)
    write("anova_twoway_drug_sex_response.csv",
          ["subject_id", "drug", "sex", "biomarker_response"], rows)


# ---- nonparametric ----------------------------------------------------------


def mannwhitney() -> None:
    """Mann-Whitney U: post-op pain score (0-10, skewed ordinal) by analgesic.
    Opioid group reports lower scores."""
    rows = []
    pid = 1
    for grp, lo_bias in (("opioid", 2.0), ("nsaid", 4.5)):
        for _ in range(120):
            # skewed integer score in [0,10]
            raw = random.gammavariate(2.0, 1.0) + lo_bias
            score = int(max(0, min(10, round(raw))))
            rows.append([f"PA{pid:04d}", grp, score])
            pid += 1
    random.shuffle(rows)
    write("mannwhitney_postop_pain_score.csv",
          ["patient_id", "analgesic", "pain_score_0_10"], rows)


def kruskalwallis() -> None:
    """Kruskal-Wallis: length of stay (skewed days) across three wards.
    Distributions differ by ward."""
    rows = []
    pid = 1
    wards = {"ICU": 6.0, "stepdown": 3.0, "general": 1.6}  # gamma scale
    for ward, scale in wards.items():
        for _ in range(90):
            days = _round(random.gammavariate(2.2, scale) + 1.0, 1)
            rows.append([f"L{pid:04d}", ward, days])
            pid += 1
    random.shuffle(rows)
    write("kruskalwallis_length_of_stay_by_ward.csv",
          ["patient_id", "ward", "length_of_stay_days"], rows)


# ---- categorical (chi-square / Fisher) --------------------------------------


def chisquare() -> None:
    """Chi-square test of independence: treatment vs recovery outcome.
    Row-level data (one patient per row) so a contingency table can be built.
    Drug has a higher recovery rate than placebo."""
    rows = []
    pid = 1
    p_recover = {"drug": 0.68, "placebo": 0.41}
    for treatment, p in p_recover.items():
        for _ in range(170):
            outcome = "recovered" if random.random() < p else "not_recovered"
            rows.append([f"C{pid:04d}", treatment, outcome])
            pid += 1
    random.shuffle(rows)
    write("chisquare_treatment_recovery.csv",
          ["patient_id", "treatment", "outcome"], rows)


def fisher_exact() -> None:
    """Fisher's exact test: rare severe adverse event in a small trial.
    Small sample + low counts -> chi-square's approximation is poor, so Fisher."""
    rows = []
    pid = 1
    # treatment: 9/24 events; control: 1/24 events
    plan = {"treatment": [True] * 9 + [False] * 15,
            "control": [True] * 1 + [False] * 23}
    for group, events in plan.items():
        random.shuffle(events)
        for ev in events:
            rows.append([f"AE{pid:03d}", group, "yes" if ev else "no"])
            pid += 1
    random.shuffle(rows)
    write("fisher_exact_severe_adverse_event.csv",
          ["patient_id", "group", "severe_adverse_event"], rows)


# ---- correlation / regression -----------------------------------------------


def correlation() -> None:
    """Pearson correlation / simple linear regression: dose vs plasma level.
    Strong positive linear relationship with noise."""
    rows = []
    for i in range(1, 221):
        dose = _round(random.uniform(5, 200), 1)
        plasma = _round(0.045 * dose + random.gauss(0, 0.6), 3)  # ug/mL
        rows.append([f"PK{i:04d}", dose, max(0.0, plasma)])
    write("correlation_dose_plasma_concentration.csv",
          ["subject_id", "dose_mg", "plasma_concentration_ug_ml"], rows)


def logistic_regression() -> None:
    """Logistic regression: lung disease ~ age + smoking (pack-years).
    Binary outcome; probability rises with age and pack-years."""
    import math

    rows = []
    for i in range(1, 301):
        age = random.randint(30, 80)
        smoker = 1 if random.random() < 0.45 else 0
        pack_years = round(random.uniform(0, 50), 1) if smoker else 0.0
        # logit: baseline low, increases with age and pack-years
        logit = -6.0 + 0.045 * age + 0.06 * pack_years
        p = 1 / (1 + math.exp(-logit))
        disease = 1 if random.random() < p else 0
        rows.append([f"R{i:04d}", age, smoker, pack_years, disease])
    write("logistic_regression_lung_disease.csv",
          ["patient_id", "age", "smoker", "pack_years", "lung_disease"], rows)


# ---- survival ---------------------------------------------------------------


def survival_logrank() -> None:
    """Log-rank test / Kaplan-Meier: survival time by treatment arm.
    Treatment arm survives longer; `event`=1 death, 0 censored (right-censored
    at the 60-month study end)."""
    rows = []
    pid = 1
    STUDY_END = 60.0
    scale = {"treatment": 42.0, "control": 24.0}  # exponential mean survival
    for arm, mean in scale.items():
        for _ in range(110):
            t = random.expovariate(1.0 / mean)
            if t >= STUDY_END:
                time, event = STUDY_END, 0  # censored at study end
            else:
                time, event = _round(t, 1), 1
            rows.append([f"SV{pid:04d}", arm, time, event])
            pid += 1
    random.shuffle(rows)
    write("survival_logrank_treatment.csv",
          ["patient_id", "arm", "time_months", "event"], rows)


if __name__ == "__main__":
    ttest_independent()
    ttest_paired()
    ttest_onesample()
    anova_oneway()
    anova_twoway()
    mannwhitney()
    kruskalwallis()
    chisquare()
    fisher_exact()
    correlation()
    logistic_regression()
    survival_logrank()
    print("\nDone. Upload any of these from the Upload tab.")
