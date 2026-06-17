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
import re
from collections.abc import Iterator
from typing import Protocol

import ollama

from ingest.errors import OllamaUnavailableError

from .steps import StepDecision

# Override with LOCUS_AGENT_MODEL. Works with any Ollama chat model, including the
# latest Qwen3 family (e.g. qwen3:8b, qwen3:14b, qwen3:30b-a3b) — a larger model
# makes the analyst noticeably smarter for research use.
DEFAULT_MODEL = os.environ.get("LOCUS_AGENT_MODEL", "qwen2.5:7b-instruct")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Remove any <think>…</think> a hybrid model (e.g. Qwen3) may emit inline."""
    return _THINK_RE.sub("", text or "").strip()


def _think_setting():
    """LOCUS_AGENT_THINK: off by default (faster, clean output). Set to
    1/true/on to let thinking models reason, or low|medium|high for a level."""
    v = os.environ.get("LOCUS_AGENT_THINK", "").strip().lower()
    if v in ("low", "medium", "high"):
        return v
    return v in ("1", "true", "on", "yes")

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
        # Thinking (Qwen3 etc.) is off by default for speed + clean output.
        self.think = _think_setting()
        self._client = client or ollama.Client(host=host)

    def warm_up(self) -> None:
        """Load the model into memory now (best-effort), so the first real
        request is fast. Safe to call in the background at startup."""
        try:
            self._client.chat(
                model=self.model,
                messages=[{"role": "user", "content": "ok"}],
                keep_alive=self.keep_alive,
                think=False,
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
                    # Force non-thinking for the structured step so we get clean
                    # schema-valid JSON (no reasoning preamble) regardless of model.
                    think=False,
                    options={"temperature": self.temperature, "num_predict": 512},
                )
            except Exception as exc:
                last_transport = exc
                continue
            try:
                return StepDecision.model_validate_json(_strip_think(resp.message.content or "{}"))
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
            # When thinking is enabled, Ollama keeps reasoning in a separate
            # `thinking` field — we only stream `content`, so the answer stays clean.
            think=self.think,
            options={"temperature": self.temperature},
        ):
            piece = chunk.message.content
            if piece:
                yield piece
