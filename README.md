# Locus — Biomedical Data Aggregator

**Turn your spreadsheets into a queryable, explorable data warehouse — without
ever changing a single value in your data.**

Locus is a desktop app for scientists and analysts. Drop in a CSV and it builds a
clean, connected view of your data that you can browse, chart, ask questions
about in plain English, and run experiments on — all on your own machine. Your
original files are preserved byte-for-byte and never altered.

---

## Why Locus

- **Your data is never changed.** Every value is stored exactly as you typed it —
  no rounding, no reformatting, no dropped rows. Locus keeps a verbatim copy of
  each file you upload and checks it on every launch.
- **Provably faithful.** Before any upload is finalized, Locus runs a battery of
  checks proving the structured version reconstructs your original data exactly.
  If anything wouldn't match, the upload is rejected — never silently "fixed."
- **Ask questions in plain English.** A built-in analyst (running a local AI model
  on your machine) can query your data, build charts, and run statistics for you —
  and it can only *read* your data, never modify it.
- **Experiment safely.** Run Python, pandas, and scikit-learn against a disposable
  copy of your data. Nothing you do in the sandbox can touch your originals.
- **Everything stays local.** No cloud, no uploads to a server. Your data and the
  AI model both run on your computer.

## Installing

Download **Biomedical Data Aggregator.dmg**, open it, and drag the app to your
Applications folder.

The app is not signed by Apple yet, so the first time you open it macOS will warn
you. Either **right-click the app and choose Open** (then confirm), or run once in
Terminal:

```bash
xattr -cr "/Applications/Biomedical Data Aggregator.app"
```

**For the AI analyst** (optional): install [Ollama](https://ollama.com/download),
then run `ollama pull qwen2.5:7b-instruct` once. If Ollama isn't set up, every
other feature still works — the app will tell you exactly what to do when you
first use the analyst.

## First launch

Double-click the app. You'll see a brief "Starting the Locus engine…" screen
while it spins up, then the dashboard opens. On the left are five tabs: **Home**,
**Upload**, **Data**, **Visualize**, and **Sandbox**. The **analyst chat** lives
behind the button in the bottom-right corner.

## Uploading your data

1. Go to **Upload** and drag a CSV onto the drop zone (or click to browse).
2. You'll see a quick preview of the first rows.
3. Pick how to structure it:
   - **Deterministic** — fast, rule-based. A good default.
   - **Agentic (local AI)** — a local model proposes the structure; every
     suggestion is verified against your actual data before it's used.
4. *(Optional)* Turn on **biomedical normalization** if you want SMILES strings
   canonicalized or gene/dose columns parsed. It's **off by default**, and when on
   it keeps your original values untouched alongside the normalized ones.
5. Click **Ingest**. Locus stores your file verbatim, builds the schema, runs its
   integrity checks, and shows you a summary.

## Browsing and exporting

The **Data** tab lets you pick a dataset, see its tables, and page through the
rows with their inferred types. Everything is read-only. Use **Export CSV** to
download what you're viewing.

## Charts

In **Visualize**, choose a dataset and a chart type (histogram, bar, plate/well
heatmap, dose-response, or scatter), pick the columns, and click **Generate**.
Charts are computed on your machine and rendered instantly; you can view the
underlying chart definition and save the image as PNG or SVG.

## Asking the analyst

Click **Ask the analyst** (bottom-right). Type a question like *"How many
compounds are in each category?"* or *"Plot dose against response."* The analyst
will answer, and show you exactly the query or chart it used. If it made a chart,
you can open it in the Visualize tab with one click. The analyst has **read-only**
access — it can explore your data but never change it.

## Running a sandbox experiment

The **Sandbox** tab gives you a Python editor working against a private, writable
**copy** of your data. Write a script — `con` is a database connection to your
data, and pandas, NumPy, matplotlib, and scikit-learn are ready to use — then
click **Run**. You'll see the output, any errors, and any plots you generated.
A banner reminds you: *you're working on a copy; nothing here affects your
original data.* Click **Destroy** when you're done.

---

## For developers

Locus is a Python backend (FastAPI + DuckDB) packaged as a desktop app via Tauri,
with a React/TypeScript/Tailwind frontend.

```bash
# backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev,bio,experiments]"
.venv/bin/python -m pytest                 # 146 tests
.venv/bin/python -m api.sidecar            # run the API locally

# frontend
npm --prefix frontend install
npm --prefix frontend run dev              # proxies /api -> localhost:8000

# desktop bundle (needs Rust + tauri-cli + PyInstaller)
make -C packaging/macos dist
```

Architecture and per-phase specs live in [docs/specs/](docs/specs/). The core
guarantee — that ingestion is non-destructive — is enforced by five QC checks
that must pass unanimously before any upload is sealed; the master check
reconstructs your original rows exactly from the structured tables.
