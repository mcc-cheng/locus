# Trial datasets

Sample CSVs for exploring Locus. Upload any of them from the **Upload** tab.
Regenerate with `python samples/generate_samples.py`.

| File | Rows | What it's good for |
|------|-----:|--------------------|
| `compounds.csv` | 255 | **Biopack** (SMILES/gene/dose) + a compound dimension, bar/scatter, agent questions |
| `plate_assay.csv` | 288 | **Heatmap** (plate row × column), dimension inference |
| `dose_response.csv` | 288 | **Dose-response curves** (log-x), grouped stats |
| `patients.csv` | 360 | **Bar/histogram**, t-tests, responder analysis |
| `gene_expression.csv` | 320 | Long/tidy format, bar by gene, treated-vs-control stats |
| `measurements.csv` | 2500 | **Scatter** + **pagination** (large table) |
| `edge_cases.csv` | 200 | Proves **verbatim storage** — nothing gets "cleaned" |

## Things to try

### `compounds.csv` — biopack + the analyst
- On upload, turn on **biomedical normalization** and set `smiles → SMILES`,
  `target_gene → gene`, `dose → dose`. After ingest, open the **Data** tab and
  look at the `fact` table: you'll see the canonical `smiles` next to `smiles_raw`
  (your original), plus `dose_value` / `dose_unit`. Benzene's
  `C1=CC=CC=C1` becomes `c1ccccc1` — and the original is still preserved.
- **Visualize:** Scatter with `x = mol_weight`, `y = logp`.
- **Ask the analyst:** *"How many compounds target each gene?"* or
  *"Which compound has the highest logP?"*

### `plate_assay.csv` — heatmap
- **Visualize → Heatmap**: `row = well_row`, `col = well_col`, `value = readout`.
  Filter to one plate first in the Data tab if you like.

### `dose_response.csv` — dose-response curve
- **Visualize → Dose-Response**: `x = concentration_uM`, `y = viability_pct`,
  `color = compound`. The x-axis is log-scaled automatically.

### `patients.csv` — distributions and statistics
- **Visualize → Histogram** of `age` or `bmi`; **Bar** of `cohort`.
- **Ask the analyst:** *"Is the biomarker level different between responders and
  non-responders?"* (it'll run a t-test in a sandbox) or *"Plot a bar chart of
  responders by cohort."*

### `measurements.csv` — scatter at scale
- **Visualize → Scatter**: `x = x`, `y = y`, `color = group`. With 2,000 rows
  this shows the server-side aggregation/cap in action.
- The **Data** tab paginates 50 rows at a time.

### `edge_cases.csv` — see that your data is never altered
- Open the **Data** tab and confirm everything is byte-for-byte:
  `00123` keeps its leading zeros, `1.0` and `1.00` stay distinct, `1e3` stays
  text, `TRUE`/`True`/`false`/`FALSE` keep their exact casing, the quoted
  `a, b, c` keeps its commas, and `$1,000` is untouched.

### Sandbox idea (any dataset)
```python
import pandas as pd
schema, table = con.execute("""
  SELECT table_schema, table_name FROM information_schema.tables
  WHERE table_name = 'raw' AND table_schema NOT IN ('information_schema') LIMIT 1
""").fetchone()
df = con.execute(f'SELECT * FROM "{schema}"."{table}"').df()
print(df.describe(include="all"))
df.hist(figsize=(10, 6))   # plots show up in the output panel
```
