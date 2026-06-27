# Phase 5 — Analyst Agent (multi-step, tool-using)

**Status:** implemented (redesigned from one-shot to a multi-step ReAct loop)
**Modules:** `src/agentic/{steps,brain,analyst,stats}.py`, `/agent/chat` in `api/rest/app.py`

A chat agent that genuinely understands the data: it explores with read-only
tools, observes results, iterates, and writes a fluent, **streamed** answer
grounded in what it found. It can also change the data — but only when the user
explicitly asks and only after they confirm (see "Mutations" below); the loop
itself has no write path.

## The loop (`analyst.py`)

Each turn runs a short ReAct loop on a local Ollama model. The brain
**auto-selects the smartest installed model** (preferring `qwen3:30b-a3b`, then
smaller Qwen3, then Qwen2.5; override with `ANNULUS_AGENT_MODEL`). On a reasoning
model it **thinks before the answer phase** (kept in a separate channel so the
answer stays clean); tool-decision steps always run non-thinking for fast,
schema-valid JSON. `ANNULUS_AGENT_THINK=0` forces non-thinking everywhere.

1. Build a **rich data context** — every dataset's tables, columns, row counts,
   and a few sample rows of `raw` — so the model "sees" the data.
2. Up to `MAX_STEPS` tool steps: the model proposes one step, the loop validates
   and executes it, and the **observation is fed back** so the model can correct
   itself (it routinely recovers from its own bad SQL).
3. **Answer phase:** a free-form chat call streams the final answer token by
   token, grounded only in the observations gathered.

## Human-in-the-loop (data quality)

Real lab data has errors; the agent must not silently skip them.

- A deterministic **data-quality inspector** (`_column_issues`) counts missing
  (null) and non-numeric values per column. Non-numeric only counts as a problem
  in numeric chart roles (a bar's categorical x is fine).
- **Chart gate:** when `make_chart` targets a column with missing/invalid values
  and the user hasn't agreed to proceed, the loop emits an `ask` event (e.g.
  *"score (2 missing of 5 rows) — how should I handle them?"*) with clickable
  options (Exclude rows / Show rows / Cancel) and ends the turn. After the user
  picks "exclude … and continue", the next turn builds the chart.
- Tools `ask_user` (pause with options) and `check_data` (inspect columns) let
  the agent raise questions proactively. `ask` events stream to the UI as
  buttons; clicking one sends it as the next message (stateless history).
- Chart column fields are normalized (stray `TRY_CAST(...)`/quotes stripped).

## Mutations (edit / delete / restructure) — propose, confirm, apply

The user can ask the analyst to change data ("delete the rows where …", "set bmi
to 0 where …", "rename column dose to dose_mg"). The agent must never change data
on its own; three guarantees enforce that:

1. **The LLM loop has no write path.** The mutation steps `edit_data`,
   `delete_data`, and `restructure_data` only *propose* a change — the loop builds
   a structured `MutationAction`, previews it (counts affected rows for
   update/delete), emits a `confirm` event with the exact SQL + Confirm/Cancel
   options, and ends the turn. Nothing is executed.
2. **Human confirmation, applied deterministically.** Clicking Confirm
   round-trips the exact previewed `MutationAction` back via
   `POST /agent/chat {confirm: …}`. The API executes it directly through
   `warehouse.mutate` (parameterized UPDATE/DELETE/ALTER) — the model is *not*
   re-run, so the applied change cannot drift from what the user approved. It
   streams a `mutation` result event then a `final` confirmation message.
3. **Intent backstop.** Even before the confirm gate, the loop refuses to propose
   a change unless the user's own message contains change intent (delete, edit,
   set, rename, drop column, …); otherwise it answers read-only.

The **preserved source copy** is never touched by a mutation, so the original
upload stays byte-for-byte recoverable. `run_sql` remains SELECT-only — DML there
is still rejected (verified by `test_agent_never_writes_canonical`).

## Tools — strict, validated (`steps.py`)

The model proposes one step per turn as JSON validated against a discriminated
union (`StepDecision`); the loop executes it — the model never runs anything:

- **run_sql** → read-only `QueryService` (SELECT-only, clone, timeout).
- **make_chart** → `VisualizationService` (server-aggregated, ≤10k rows).
- **run_stat** → a *templated* script (model picks test + columns only) in a
  **disposable sandbox**.
- **make_figure** → free Python (matplotlib/pandas) in a **disposable sandbox**,
  returning an inline PNG — for report figures of computed metrics that the
  chart-spec tool can't express. Wrappers/fences/backticks are normalized.
- **answer** → stop exploring and write the answer.

Because every tool call is validated and runs through the read-only services or a
sandbox, the agent can never modify data — verified by tests (a "run_sql" that is
really DML is rejected; the canonical's bytes are unchanged).

## `/agent/chat` (streaming)

`POST /agent/chat` with `{message, history}` (full history each request — no
server session). Streams NDJSON events: `step` (tool + thought + sql + summary),
`chart` (spec + chart_request), `token` (answer deltas), `final` (full answer),
and `error`. The UI renders a live "thinking" trace, the streaming answer, and any
charts (with **Open in Visualize**).

## Brain (`brain.py`)

`OllamaBrain` exposes `decide_step` (structured, schema-constrained) and
`stream_answer` (free-form, streamed), plus availability gating. Injectable
(`create_app(root, brain_factory=...)`) so the whole loop is tested with a fake
brain; one real-Ollama test asserts a grounded answer.
