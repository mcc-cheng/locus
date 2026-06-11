"""Ollama-backed proposer for the agentic engine (Phase 2.2).

Talks to a LOCAL Ollama running ``qwen2.5:7b-instruct`` by default. If Ollama is
not running, or the model is not pulled, it raises ``OllamaUnavailableError``
with actionable setup instructions — it NEVER silently falls back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import ollama

from .errors import OllamaUnavailableError, ProposalError
from .proposal import ModelProposal

DEFAULT_MODEL = "qwen2.5:7b-instruct"

_SERVER_DOWN = """\
The agentic ingestion engine needs a local Ollama server, but none is reachable.

To use it:
  1. Install Ollama:  https://ollama.com/download
  2. Start it:        run `ollama serve` (or launch the Ollama app)
  3. Pull the model:  `ollama pull {model}`

Or pick the Deterministic engine, which needs no model.
"""

_MODEL_MISSING = """\
Ollama is running, but the required model `{model}` is not installed.

Pull it once with:
  ollama pull {model}

Or pick the Deterministic engine, which needs no model.
"""

_SYSTEM = (
    "You are a careful data architect. Given a profile of a flat CSV table, you "
    "propose a star-schema design: the fact grain, the fact's identifying column, "
    "and which columns group into dimension tables. You may ONLY use column names "
    "exactly as given. Never invent columns. A dimension's `key` must identify its "
    "`attributes` (each key value maps to one attribute value). Respond with JSON "
    "only, matching the provided schema."
)


@dataclass
class OllamaConfig:
    model: str = DEFAULT_MODEL
    host: str | None = None  # None => ollama default (http://localhost:11434)
    temperature: float = 0.0  # determinism: same profile -> same proposal
    num_retries: int = 2


def _normalize(name: str) -> str:
    return name[: -len(":latest")] if name.endswith(":latest") else name


class OllamaClient:
    """A :class:`Proposer` backed by a local Ollama instance."""

    def __init__(self, config: OllamaConfig | None = None, *, client=None) -> None:
        self.config = config or OllamaConfig()
        self._client = client or ollama.Client(host=self.config.host)

    # ---- availability ----------------------------------------------------

    def ensure_available(self) -> None:
        try:
            resp = self._client.list()
        except Exception as exc:  # connection refused, timeout, etc.
            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.config.model)) from exc
        installed = {_normalize(m.model) for m in resp.models if m.model}
        if _normalize(self.config.model) not in installed:
            raise OllamaUnavailableError(_MODEL_MISSING.format(model=self.config.model))

    # ---- proposal --------------------------------------------------------

    def propose(self, profile: dict) -> ModelProposal:
        self.ensure_available()
        schema = ModelProposal.model_json_schema()
        user = (
            "Table profile (all columns are stored as text):\n"
            + json.dumps(profile, ensure_ascii=False, indent=2)
            + "\n\nReturn a JSON object with keys: grain (string), primary_key "
            "(string or null), dimensions (array of {key, attributes, name})."
        )
        last_transport: Exception | None = None
        last_parse: Exception | None = None
        for _ in range(max(1, self.config.num_retries)):
            try:
                resp = self._client.chat(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    format=schema,
                    options={"temperature": self.config.temperature},
                )
            except Exception as exc:  # connection dropped mid-run, etc.
                last_transport = exc
                continue
            try:
                content = resp.message.content or "{}"
                return ModelProposal.model_validate_json(content)
            except Exception as exc:  # malformed / non-conforming JSON
                last_parse = exc
                continue
        if last_transport is not None and last_parse is None:
            # Pure transport failure -> availability problem, block.
            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.config.model))
        # Reachable but unusable output -> let the engine degrade and record it.
        raise ProposalError(f"Ollama returned no schema-valid proposal after retries: {last_parse}")
