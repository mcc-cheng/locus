"""The semantic proposal an LLM is allowed to make (Phase 2.2).

This is the ONLY surface where the model has influence. It proposes *semantics*
— what one fact row means (grain), which column identifies the fact, and which
columns group into dimensions. It never touches data and never decides
mechanics. Deterministic code validates every field against the real data
before anything is built.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ProposedDimension(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(description="The column that identifies one dimension row.")
    attributes: list[str] = Field(
        default_factory=list, description="Columns describing the entity keyed by `key`."
    )
    name: str = Field(default="", description="Optional human label; sanitized before use.")


class ModelProposal(BaseModel):
    """The structured output we require from the model (extra fields ignored)."""

    model_config = ConfigDict(extra="ignore")

    grain: str = Field(default="", description="Plain-English description of one fact row.")
    primary_key: str | None = Field(default=None, description="Proposed fact PK column.")
    dimensions: list[ProposedDimension] = Field(default_factory=list)


class Proposer(Protocol):
    """Anything that can supply a semantic proposal for a profiled table.

    Implemented by ``OllamaClient``; tests inject fakes. ``ensure_available`` must
    raise ``OllamaUnavailableError`` (or similar) when the backend is unreachable
    — the engine blocks rather than silently falling back.
    """

    def ensure_available(self) -> None: ...

    def propose(self, profile: dict) -> ModelProposal: ...
