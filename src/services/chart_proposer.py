"""LLM-backed chart proposer for agentic suggestions.

Mirrors the agentic-ingest contract (``ingest/proposal.py`` +
``ingest/ollama_client.py``): a local LLM proposes *which* charts to draw and
*why*, choosing from a fixed palette of renderable chart types and using only the
real column names it is given. The service validates every proposal against the
actual data and drops anything unrenderable — a hallucinated proposal degrades
gracefully, it never produces a broken chart.

If Ollama is unavailable the proposer raises ``OllamaUnavailableError`` and the
caller falls back to deterministic suggestions — it NEVER silently substitutes.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ingest.errors import OllamaUnavailableError, ProposalError

# The chart types the app can actually render (server-side builders exist).
PALETTE = (
    "histogram",
    "bar",
    "heatmap",
    "dose_response",
    "scatter",
    "box",
    "line",
    "grouped_bar",
    "correlation_matrix",
)


class ProposedChart(BaseModel):
    """One chart the model proposes. Extra fields ignored; everything but
    ``type`` and ``title`` is optional and validated downstream."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(description="One of the allowed chart types.")
    title: str = Field(default="", description="Short human title for the chart.")
    rationale: str = Field(default="", description="Why this chart is worth looking at.")
    x: str | None = None
    y: str | None = None
    color: str | None = None
    row: str | None = None
    col: str | None = None
    value: str | None = None
    aggregate: str | None = None


class ChartProposalSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    charts: list[ProposedChart] = Field(default_factory=list)


class ChartProposer(Protocol):
    """Anything that can propose charts for a profiled table. Tests inject fakes."""

    def ensure_available(self) -> None: ...

    def propose(self, profile: dict) -> ChartProposalSet: ...


_SYSTEM = (
    "You are a data-visualization expert. Given a profile of a table, propose a "
    "small set (3-6) of the most insightful charts. You decide which charts and "
    "why. Rules: (1) use ONLY the chart types listed; (2) reference ONLY column "
    "names given in the profile, exactly; (3) put continuous/numeric columns on "
    "numeric roles and low-cardinality columns on category roles; (4) give each "
    "chart a short title and a one-sentence rationale explaining the insight. "
    "Respond with JSON only, matching the schema.\n\n"
    "Chart types and their roles:\n"
    "- histogram: x=numeric\n"
    "- bar: x=category (optional y=numeric with aggregate)\n"
    "- box: x=category, y=numeric (distribution per group)\n"
    "- line: x=numeric/ordered, y=numeric (optional color=series)\n"
    "- scatter: x=numeric, y=numeric (optional color)\n"
    "- grouped_bar: x=category, color=category (optional y=numeric with aggregate)\n"
    "- dose_response: x=numeric dose, y=numeric response (optional color=series)\n"
    "- heatmap: row, col, value (spatial/plate layout)\n"
    "- correlation_matrix: no columns needed (uses all numeric columns)\n"
)


class OllamaChartProposer:
    """A :class:`ChartProposer` backed by a local Ollama instance, on the same
    model the analyst uses (``LOCUS_AGENT_MODEL`` or auto-pick)."""

    def __init__(self, *, model: str | None = None, client=None, num_retries: int = 2) -> None:
        # Import lazily so importing this module never requires ollama.
        import ollama

        from agentic.brain import _resolve_model

        self.model = model or _resolve_model()
        self._client = client or ollama.Client()
        self.num_retries = num_retries

    def ensure_available(self) -> None:
        from ingest.ollama_client import _MODEL_MISSING, _SERVER_DOWN, _normalize

        try:
            resp = self._client.list()
        except Exception as exc:
            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.model)) from exc
        installed = {_normalize(m.model) for m in resp.models if m.model}
        if _normalize(self.model) not in installed:
            raise OllamaUnavailableError(_MODEL_MISSING.format(model=self.model))

    def propose(self, profile: dict) -> ChartProposalSet:
        self.ensure_available()
        schema = ChartProposalSet.model_json_schema()
        user = (
            "Table profile:\n"
            + json.dumps(profile, ensure_ascii=False, indent=2)
            + "\n\nReturn JSON: {\"charts\": [{type, title, rationale, x, y, color, "
            "row, col, value, aggregate}]}. Omit roles a chart does not use."
        )
        last_transport: Exception | None = None
        last_parse: Exception | None = None
        for _ in range(max(1, self.num_retries)):
            try:
                resp = self._client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    format=schema,
                    options={"temperature": 0.2},
                )
            except Exception as exc:
                last_transport = exc
                continue
            try:
                content = resp.message.content or "{}"
                return ChartProposalSet.model_validate_json(content)
            except Exception as exc:
                last_parse = exc
                continue
        if last_transport is not None and last_parse is None:
            from ingest.ollama_client import _SERVER_DOWN

            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.model))
        raise ProposalError(f"Ollama returned no schema-valid chart proposal: {last_parse}")
