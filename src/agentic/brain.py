"""The agent's decision backend (Phase 5.1).

A ``Brain`` turns a system+user prompt into a validated ``AgentDecision``. The
Ollama-backed implementation runs locally; tests inject fakes. The loop (the
analyst) validates and executes — the brain only proposes.
"""

from __future__ import annotations

from typing import Protocol

import ollama

from ingest.errors import OllamaUnavailableError

from .actions import AgentDecision

DEFAULT_MODEL = "qwen2.5:7b-instruct"

_SERVER_DOWN = """\
The analyst agent needs a local Ollama server, but none is reachable.
  1. Install Ollama:  https://ollama.com/download
  2. Start it:        run `ollama serve` (or launch the Ollama app)
  3. Pull the model:  `ollama pull {model}`
"""
_MODEL_MISSING = "Ollama is running, but `{model}` is not installed. Run: ollama pull {model}"


class AgentError(Exception):
    """The brain could not produce a valid decision."""


class Brain(Protocol):
    def decide(self, system: str, user: str) -> AgentDecision: ...


def _normalize(name: str) -> str:
    return name[: -len(":latest")] if name.endswith(":latest") else name


class OllamaBrain:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        host: str | None = None,
        client=None,
        temperature: float = 0.0,
        num_retries: int = 3,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.num_retries = num_retries
        self._client = client or ollama.Client(host=host)

    def ensure_available(self) -> None:
        try:
            resp = self._client.list()
        except Exception as exc:
            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.model)) from exc
        installed = {_normalize(m.model) for m in resp.models if m.model}
        if _normalize(self.model) not in installed:
            raise OllamaUnavailableError(_MODEL_MISSING.format(model=self.model))

    def decide(self, system: str, user: str) -> AgentDecision:
        self.ensure_available()
        schema = AgentDecision.model_json_schema()
        last_parse: Exception | None = None
        last_transport: Exception | None = None
        for _ in range(max(1, self.num_retries)):
            try:
                resp = self._client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    format=schema,
                    options={"temperature": self.temperature},
                )
            except Exception as exc:
                last_transport = exc
                continue
            try:
                return AgentDecision.model_validate_json(resp.message.content or "{}")
            except Exception as exc:
                last_parse = exc
                continue
        if last_transport is not None and last_parse is None:
            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.model))
        raise AgentError(f"model did not produce a valid action after retries: {last_parse}")
