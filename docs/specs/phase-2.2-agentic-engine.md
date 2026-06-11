# Phase 2.2 — Agentic Ingestion Engine (Ollama)

**Status:** implemented
**Modules:** `src/ingest/{agentic,ollama_client,proposal}.py`

## Goal

Use a LOCAL LLM (Ollama, `qwen2.5:7b-instruct`) to make **only semantic
decisions**: the fact grain, the fact's identifying column, and which columns
group into dimensions. Deterministic code handles **all** mechanical assembly and
verification. Same five QC checks as the deterministic engine — unanimous pass
required. If Ollama is not running (or the model isn't pulled), **block** with
setup instructions; never silently fall back.

## Division of responsibility

| Concern | Owner |
|---------|-------|
| Fact grain, PK candidate, dimension groupings, biopack opt-in hints | **Model** (`ModelProposal`) |
| Profiling the table, validating every proposal against real data, table assembly, QC, sealing | **Deterministic code** |

The model's influence is confined to a single validated structure
(`ModelProposal`: `grain`, `primary_key`, `dimensions[]`). It never sees or
touches values beyond a small profile, and never decides mechanics.

## Validation — the model proposes, the data disposes

`build_contract_from_proposal` accepts a proposed field only if it holds against
the actual data:

- **PK** accepted only if the named column is non-null and fully unique;
  otherwise the deterministic PK inference is used (recorded as a note).
- **Dimension** accepted only if its key is an existing, non-null, **repeating**
  column, and each attribute's **functional dependency** `key -> attribute`
  genuinely holds. Hallucinated columns, false dependencies, degenerate 1:1
  keys, and double-claims are dropped — each with an audit note.

Because assembly and the five QC checks are identical to Phase 2.1, a bad
proposal can at worst be *dropped* (degrading toward a flat fact) — it can never
alter or lose data. Reconstruction-equals-raw is still the master gate.

## Availability — block, never fall back

`OllamaClient.ensure_available()` is called **before any data is touched**:

- Server unreachable → `OllamaUnavailableError` with install/start/pull steps.
- Model not pulled → `OllamaUnavailableError` with the `ollama pull` step.

A *transport* failure mid-run also raises `OllamaUnavailableError` (blocks). A
*reachable-but-unusable* model output (malformed JSON after retries) raises
`ProposalError`, which the engine handles by degrading to the deterministic
structure — loudly recorded in the audit `notes`. The distinction matters: we
block on availability, but we don't fail a perfectly good CSV because a 7B model
emitted bad JSON once.

## Artifacts

On successful seal: `<root>/contracts/<section>.contract.json` (the sealed
Storage Contract) and `<root>/audit/<section>.audit.json` (engine, model name,
hash, contract, decision log, override notes, QC verdict). Contract + engine are
also persisted in `_locus.sections`.

## Testing

The proposer is an injectable `Proposer` protocol, so the validation/assembly/QC
path is tested deterministically with a `FakeProposer` (valid proposals, false
FDs, hallucinated columns, bad PKs, `ProposalError` degradation, availability
blocking). One end-to-end test runs the real `qwen2.5:7b-instruct` and asserts
losslessness regardless of the schema it proposes; it skips if the model isn't
installed.
