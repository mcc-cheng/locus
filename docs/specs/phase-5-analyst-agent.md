# Phase 5 — Analyst Agent (multi-step, tool-using)

**Status:** implemented (redesigned from one-shot to a multi-step ReAct loop)
**Modules:** `src/agentic/{steps,brain,analyst,stats}.py`, `/agent/chat` in `api/rest/app.py`

A chat agent with **read-only** access that genuinely understands the data: it
explores with tools, observes results, iterates, and writes a fluent, **streamed**
answer grounded in what it found. It never writes to the canonical DB.

## The loop (`analyst.py`)

Each turn runs a short ReAct loop on a local Ollama model (`qwen2.5:7b-instruct`):

1. Build a **rich data context** — every dataset's tables, columns, row counts,
   and a few sample rows of `raw` — so the model "sees" the data.
2. Up to `MAX_STEPS` tool steps: the model proposes one step, the loop validates
   and executes it, and the **observation is fed back** so the model can correct
   itself (it routinely recovers from its own bad SQL).
3. **Answer phase:** a free-form chat call streams the final answer token by
   token, grounded only in the observations gathered.

## Tools — strict, validated (`steps.py`)

The model proposes one step per turn as JSON validated against a discriminated
union (`StepDecision`); the loop executes it — the model never runs anything:

- **run_sql** → read-only `QueryService` (SELECT-only, clone, timeout).
- **make_chart** → `VisualizationService` (server-aggregated, ≤10k rows).
- **run_stat** → a *templated* script (model picks test + columns only) in a
  **disposable sandbox**.
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
