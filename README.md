# Annulus AI

**Turn your spreadsheets into a queryable, explorable data warehouse — without
ever changing a single value in your data.**

Annulus is a desktop app for scientists and analysts. Drop in a CSV and it builds a
clean, connected view of your data that you can browse, chart, ask questions
about in plain English, and run experiments on — all on your own machine. Your
original files are preserved byte-for-byte and never altered.

---

## Why Annulus

- **Your original is never changed.** Every value is ingested exactly as you typed
  it — no rounding, no reformatting, no dropped rows. Annulus keeps a verbatim copy
  of each file you upload and checks it on every launch, so even after you edit the
  working data it stays recoverable.
- **Provably faithful.** Before any upload is finalized, Annulus runs a battery of
  checks proving the structured version reconstructs your original data exactly.
  If anything wouldn't match, the upload is rejected — never silently "fixed."
- **Ask questions in plain English.** A built-in analyst (running a local AI model
  on your machine) can query your data, build charts, and run statistics for you.
  It can also edit, delete, or restructure your data when you ask it to — but
  *only* when you ask, and *only* after you confirm the exact change; it never
  modifies anything on its own, and your original upload is always preserved.
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
then pull a model once. The analyst **auto-selects the smartest model you have
installed** (it prefers `qwen3:30b-a3b` — a large but fast MoE that reasons well —
then smaller Qwen3, then Qwen2.5, falling back to `qwen2.5:7b-instruct`). So just:

```bash
ollama pull qwen3:30b-a3b     # recommended — best balance of smart + fast
# or a lighter option:
ollama pull qwen3:8b
```

You can pin a specific model with `ANNULUS_AGENT_MODEL`:

```bash
ANNULUS_AGENT_MODEL=qwen3:8b ./dev.sh          # force a particular model
ANNULUS_AGENT_THINK=0 ./dev.sh                 # turn reasoning off (faster, terser)
```

On a reasoning model (Qwen3) the analyst **thinks before answering by default** —
the chain-of-thought is kept in a separate channel so the final answer stays
clean, while accuracy improves. This is a no-op on non-reasoning models (Qwen2.5).
Set `ANNULUS_AGENT_THINK=0` to trade some quality for speed. If Ollama isn't set up,
every other feature still works.

## First launch

Double-click the app. You'll see a brief "Starting the Annulus engine…" screen
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
5. Click **Ingest**. Annulus stores your file verbatim, builds the schema, runs its
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
you can open it in the Visualize tab with one click.

**Asking it to change data.** You can also tell the analyst to edit, delete, or
restructure data — e.g. *"delete the rows where cohort is control"*, *"set bmi to
0 where it's missing"*, or *"rename the column dose to dose_mg"*. The analyst
never changes anything by itself: it shows you the exact change (the statement it
will run and how many rows it affects) with **Confirm** / **Cancel** buttons, and
applies it only after you click Confirm. Your original uploaded file is always
preserved byte-for-byte, so any edit is recoverable.

## Running a sandbox experiment

The **Sandbox** tab gives you a Python editor working against a private, writable
**copy** of your data. Write a script — `con` is a database connection to your
data, and pandas, NumPy, matplotlib, and scikit-learn are ready to use — then
click **Run**. You'll see the output, any errors, and any plots you generated.
A banner reminds you: *you're working on a copy; nothing here affects your
original data.* Click **Destroy** when you're done.

---

## For developers

Annulus is a Python backend (FastAPI + DuckDB) packaged as a desktop app via Tauri,
with a React/TypeScript/Tailwind frontend.

```bash
# backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev,bio,experiments]"
.venv/bin/python -m pytest                 # 173 tests
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
