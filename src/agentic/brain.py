"""The agent's Ollama backend.

Two capabilities:
  * ``decide_step`` — structured: returns a validated ``StepDecision`` (the model
    proposes a tool; the loop validates and executes).
  * ``stream_answer`` — free-form: streams the final natural-language answer token
    by token, grounded in the observations the loop gathered.

Tests inject fakes implementing the ``Brain`` protocol.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Protocol

import ollama

from ingest.errors import OllamaUnavailableError

from .steps import StepDecision

# Override with LOCUS_AGENT_MODEL — a larger model (e.g. qwen2.5:14b-instruct or
# qwen2.5:32b-instruct) makes the analyst noticeably smarter for research use.
DEFAULT_MODEL = os.environ.get("LOCUS_AGENT_MODEL", "qwen2.5:7b-instruct")

_SERVER_DOWN = """\
The analyst needs a local Ollama server, but none is reachable.
  1. Install Ollama:  https://ollama.com/download
  2. Start it:        run `ollama serve` (or launch the Ollama app)
  3. Pull the model:  `ollama pull {model}`
"""
_MODEL_MISSING = "Ollama is running, but `{model}` is not installed. Run: ollama pull {model}"


class AgentError(Exception):
    """The brain could not produce a valid decision."""


class Brain(Protocol):
    def ensure_available(self) -> None: ...
    def decide_step(self, system: str, messages: list[dict]) -> StepDecision: ...
    def stream_answer(self, system: str, messages: list[dict]) -> Iterator[str]: ...


def _normalize(name: str) -> str:
    return name[: -len(":latest")] if name.endswith(":latest") else name


class OllamaBrain:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        host: str | None = None,
        client=None,
        temperature: float = 0.1,
        num_retries: int = 3,
        keep_alive: str = "30m",
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.num_retries = num_retries
        # Keep the model resident in Ollama between calls so we don't pay the
        # cold-load penalty on every step — the single biggest latency win.
        self.keep_alive = keep_alive
        self._client = client or ollama.Client(host=host)

    def warm_up(self) -> None:
        """Load the model into memory now (best-effort), so the first real
        request is fast. Safe to call in the background at startup."""
        try:
            self._client.chat(
                model=self.model,
                messages=[{"role": "user", "content": "ok"}],
                keep_alive=self.keep_alive,
                options={"num_predict": 1},
            )
        except Exception:
            pass

    def ensure_available(self) -> None:
        try:
            resp = self._client.list()
        except Exception as exc:
            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.model)) from exc
        installed = {_normalize(m.model) for m in resp.models if m.model}
        if _normalize(self.model) not in installed:
            raise OllamaUnavailableError(_MODEL_MISSING.format(model=self.model))

    def decide_step(self, system: str, messages: list[dict]) -> StepDecision:
        self.ensure_available()
        schema = StepDecision.model_json_schema()
        convo = [{"role": "system", "content": system}, *messages]
        last_parse: Exception | None = None
        last_transport: Exception | None = None
        for _ in range(max(1, self.num_retries)):
            try:
                resp = self._client.chat(
                    model=self.model,
                    messages=convo,
                    format=schema,
                    keep_alive=self.keep_alive,
                    options={"temperature": self.temperature, "num_predict": 512},
                )
            except Exception as exc:
                last_transport = exc
                continue
            try:
                return StepDecision.model_validate_json(resp.message.content or "{}")
            except Exception as exc:
                last_parse = exc
                continue
        if last_transport is not None and last_parse is None:
            raise OllamaUnavailableError(_SERVER_DOWN.format(model=self.model))
        raise AgentError(f"model did not return a valid step after retries: {last_parse}")

    def stream_answer(self, system: str, messages: list[dict]) -> Iterator[str]:
        self.ensure_available()
        convo = [{"role": "system", "content": system}, *messages]
        for chunk in self._client.chat(
            model=self.model,
            messages=convo,
            stream=True,
            keep_alive=self.keep_alive,
            options={"temperature": self.temperature},
        ):
            piece = chunk.message.content
            if piece:
                yield piece
