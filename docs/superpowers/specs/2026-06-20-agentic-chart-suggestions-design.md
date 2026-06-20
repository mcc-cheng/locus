# Agentic Chart Suggestions — Design

**Date:** 2026-06-20
**Status:** Approved for build

## Goal

Replace the purely deterministic chart suggestions in the Visualize tab with
**agent-generated** suggestions: a local LLM reads a profile of the ingested data
and decides — with full freedom over *which* charts and *why* — what is worth
plotting. Deterministic suggestions remain as an offline fallback.

## Reconciling "agent decides freely" with rendering

The app renders charts via **server-side builders** (each runs a DuckDB
aggregation and emits a Vega-Lite spec; full tables never reach the browser). A
chart type with no builder cannot render. So the agent has full authority over
*which* charts, *which columns*, and *why*, but it picks a chart `type` from a
**palette of renderable types**. Every proposal is validated against the real
data; anything unrenderable or hallucinated is dropped and logged. This mirrors
the existing agentic-ingest contract: *propose → validate against real data →
drop-invalid → degrade gracefully*.

## Chart palette

Existing 5 (unchanged): `histogram`, `bar`, `heatmap`, `dose_response`, `scatter`.

Four new server-side builders in `visualization_service.py`:

| type | roles | aggregation |
|---|---|---|
| `box` | x=category, y=numeric | server-computes 5-number summary per group (`quantile_cont`); rendered as a layered rule+bar+tick boxplot (keeps payload to one row/group) |
| `line` | x=numeric/ordered, y=numeric, color=optional series | `avg(y)` grouped by x (and series), ordered by x |
| `grouped_bar` | x=category, color=category, y=optional numeric | `count` or `agg(y)` grouped by (x, color); grouped via `xOffset` |
| `correlation_matrix` | none (uses all numeric columns, capped at 12) | pairwise `corr()` → long-form rows → rect heatmap, diverging scale |

## Components

- **`services/chart_proposer.py`** (new) — mirrors `ingest/proposal.py` +
  `ingest/ollama_client.py`. Pydantic `ProposedChart` (`type, x, y, color, row,
  col, value, aggregate, title, rationale`) and `ChartProposalSet`. A
  `ChartProposer` Protocol; `OllamaChartProposer` implements it (structured JSON
  output, retries, `format=schema`). Model resolved via the existing
  `LOCUS_AGENT_MODEL`/auto-pick logic (shared with the analyst).
- **`services/visualization_service.py`** — add the 4 builders; add
  `_model_profile()` (column stats + sample values for the prompt, built from
  `QueryService`); add `generate_suggestions(proposer)` → validated
  `list[ChartSuggestion]`. Keep `suggest()` as the deterministic fallback.
- **Validation** (deterministic, in the service): type ∈ palette; every
  referenced column exists in the table; numeric roles are actually numeric (per
  the profile); per-type required-role check; de-dup; cap at 6.
- **`services/suggestions_store.py`** (new) — atomic read/write of
  `<root>/suggestions/<section>.<table>.suggestions.json` (same pattern as
  `audit.py`).
- **`services/models.py`** — extend `ChartType` Literal with the 4 new types;
  add optional `rationale: str | None` to `ChartSuggestion`.

## Timing / caching / fallback

- **At ingest** (in the `/ingest` handler, *after* the section is sealed and the
  warehouse is closed — outside the QC transaction so it can never fail an
  ingest): best-effort generate suggestions for the `raw` table and write the
  cache file. Wrapped in try/except; on `OllamaUnavailableError` /
  `ProposalError` / too-few-valid, write nothing.
- **`GET /visualize/suggestions`**: if the cache file exists, return it;
  otherwise compute the **deterministic** suggester live (current behavior,
  unchanged). So no Ollama at ingest ⇒ no cache ⇒ deterministic at read time.

## Frontend

- `types.ts`: extend `ChartType`; add `rationale?: string` to `ChartSuggestion`.
- `Visualize.tsx`: add `CHARTS` entries + `CHART_GLYPH` glyphs for the 4 new
  types (so the custom builder can make them too); render `s.rationale` under the
  suggestion title when present.
- No trigger change: the tab still fetches on dataset/table selection, but now
  receives the richer cached results.

## Testing

- Builder unit tests for `box`, `line`, `grouped_bar`, `correlation_matrix`
  (spec shape + aggregation correctness), mirroring existing viz tests.
- `ChartProposer` validation tests with a **fake proposer**: hallucinated column
  → dropped; bad type → dropped; non-numeric where numeric required → dropped;
  valid → passes; empty/garbage → caller falls back to deterministic.
- Cache round-trip + endpoint: cache present → returns agent suggestions; absent
  → returns deterministic.

## Non-goals

- No new trigger UX (no "regenerate" button) in v1.
- The agent is not allowed to emit raw Vega-Lite or invent chart types outside
  the palette.
