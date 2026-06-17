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

def _normalize(name: str) -> str:
    return name[: -len(":latest")] if name.endswith(":latest") else name


# When LOCUS_AGENT_MODEL is unset, auto-pick the best installed model in this
# order (smartest first). Qwen3 reasons better; 30b-a3b is a fast MoE.
_PREFERRED = [
    "qwen3:32b",
    "qwen3:30b-a3b",
    "qwen3:14b",
    "qwen3:8b",
    "qwen2.5:32b-instruct",
    "qwen2.5:14b-instruct",
    "qwen2.5:7b-instruct",
]
_resolved_model: str | None = None


def _resolve_model() -> str:
    """LOCUS_AGENT_MODEL if set, else the best installed model (cached)."""
    env = os.environ.get("LOCUS_AGENT_MODEL")
    if env:
        return env
    global _resolved_model
    if _resolved_model:
        return _resolved_model
    try:
        installed = {_normalize(m.model) for m in ollama.Client().list().models if m.model}
        _resolved_model = next((p for p in _PREFERRED if p in installed), "qwen2.5:7b-instruct")
    except Exception:
        _resolved_model = "qwen2.5:7b-instruct"
    return _resolved_model


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Remove any <think>…</think> a hybrid model (e.g. Qwen3) may emit inline."""
    return _THINK_RE.sub("", text or "").strip()


def _answer_think_setting():
    """Whether the model 'thinks' before writing the final answer. ON by default:
    on a reasoning model (Qwen3) thinking keeps the chain-of-thought in a separate
    channel so the answer is clean — with it OFF, Qwen3 dumps its reasoning into
    the answer text. It's a no-op on non-reasoning models (Qwen2.5). Set
    LOCUS_AGENT_THINK=0 to force off (faster but answers may be verbose)."""
    v = os.environ.get("LOCUS_AGENT_THINK")
    if v is None:
        return True
    v = v.strip().lower()
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


class OllamaBrain:
    def __init__(
        self,
        model: str | None = None,
        *,
        host: str | None = None,
        client=None,
        temperature: float = 0.1,
        num_retries: int = 3,
        keep_alive: str = "30m",
        think: bool | str | None = None,
    ) -> None:
        self.model = model or _resolve_model()
        self.temperature = temperature
        self.num_retries = num_retries
        # Keep the model resident in Ollama between calls so we don't pay the
        # cold-load penalty on every step — the single biggest latency win.
        self.keep_alive = keep_alive
        # Reason before writing the answer (clean on Qwen3; no-op otherwise).
        # Tool decisions stay non-thinking for speed + clean JSON.
        self.answer_think = think if think is not None else _answer_think_setting()
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
            think=self.answer_think,
            options={"temperature": self.temperature},
        ):
            piece = chunk.message.content
            if piece:
                yield piece
