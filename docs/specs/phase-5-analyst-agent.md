# Phase 5 — Analyst Agent

**Status:** implemented
**Modules:** `src/agentic/{actions,stats,brain,analyst}.py`, `/agent/chat` in `api/rest/app.py`

A chat agent with **read-only** access to the warehouse. It never writes to the
canonical DB or any non-sandbox resource.

## 5.1 Agent core (`analyst.py`)

Each turn: build a compact schema context (sections → tables → columns), ask the
**brain** (local Ollama, `qwen2.5:7b-instruct`) for one action, then **the loop
validates and executes** — the model never executes anything. The agent always
returns the natural-language response, the SQL or chart spec it used, and the
result.

Execution paths are all non-writing:
- **query** → read-only `QueryService` (SELECT-only, clone, timeout).
- **chart** → `VisualizationService` (server-aggregated, ≤10k rows). The agent
  picks type + columns; it can never embed full-table data in a spec.
- **stat_test** → a *templated* script (we build the code; the model only picks a
  test name + columns) run in a **sandbox** clone.
- **narrative** → no data access.

Service errors are returned in the response (`error` field), not raised — the
chat keeps going.

## 5.2 Action union (`actions.py`)

Exactly four shapes, as a strict Pydantic **discriminated union** (`extra=forbid`,
frozen): `QueryAction` (SQL SELECT), `ChartAction` (chart type + columns),
`StatTestAction` (named test + columns + `sandbox_id`), `NarrativeAction` (text).
Anything else — unknown `type`, extra/missing fields — raises `ValidationError`
and is rejected **before execution**. Allowed tests: `ttest_ind`, `ttest_rel`,
`mannwhitneyu`, `pearsonr`, `spearmanr`, `f_oneway`.

## 5.3 `/agent/chat` (`api/rest/app.py`)

`POST /agent/chat` with `{message, history}`. The **full conversation history is
passed each request — no server-side session state**. Returns a **streaming**
NDJSON response with staged events: `action` (action_type + sql/spec), `result`,
then `message`. Availability failures stream an `error` event. The brain is
injectable (`create_app(root, brain_factory=...)`) for testing.

## Guarantees under test

- The agent never writes the canonical DB: a "query" that is really DDL/DML is
  rejected by the query service; the canonical's bytes are unchanged.
- Malformed/illegal actions are rejected by the union before execution.
- Real Ollama produces a valid one-of-four action (test skips if unavailable).
