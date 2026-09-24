"""Claude API access. Every call returns a validated Pydantic object plus usage for cost tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from .config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens: (input, output, cache read, cache write 5m)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.50),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
}

# Models that support server-side refusal fallbacks with `fallbacks: "default"`.
_FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
# Models that take adaptive thinking + effort.
_ADAPTIVE_MODELS_PREFIXES = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-opus-4-8", "claude-opus-4-7")


class LLMError(Exception):
    """The model could not produce a usable answer (refusal, truncation, API failure)."""


@dataclass
class Usage:
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    def add(self, other: Usage) -> None:
        self.model = self.model or other.model
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out
        self.cost_usd += other.cost_usd


@dataclass
class LLMResult:
    parsed: Any
    usage: Usage


class LLM(Protocol):
    def structured(
        self,
        *,
        role: str,
        system: list[dict[str, Any]],
        content: list[dict[str, Any]],
        schema: type[T],
        max_tokens: int = 16000,
    ) -> LLMResult: ...


def _cost(model: str, usage: Any) -> Usage:
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES["claude-opus-5"])
    tin = usage.input_tokens or 0
    tout = usage.output_tokens or 0
    tread = getattr(usage, "cache_read_input_tokens", 0) or 0
    twrite = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cost = (tin * p_in + tout * p_out + tread * p_read + twrite * p_write) / 1_000_000
    return Usage(model=model, tokens_in=tin + tread + twrite, tokens_out=tout, cost_usd=cost)


class AnthropicLLM:
    """Calls Claude with structured outputs.

    role="write" uses the large model (kit building, ad writing); role="check" uses the small model (review pass).
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(max_retries=2, timeout=120.0)
        return self._client

    def structured(
        self,
        *,
        role: str,
        system: list[dict[str, Any]],
        content: list[dict[str, Any]],
        schema: type[T],
        max_tokens: int = 16000,
    ) -> LLMResult:
        model = settings.write_model if role == "write" else settings.check_model
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_format": schema,
        }
        betas: list[str] = []
        if model.startswith(_ADAPTIVE_MODELS_PREFIXES):
            kwargs["thinking"] = {"type": "adaptive"}
            if role == "write":
                kwargs["output_config"] = {"effort": settings.write_effort}
        if model in _FALLBACK_MODELS:
            betas.append("server-side-fallback-2026-07-01")
            kwargs["fallbacks"] = "default"
        if betas:
            kwargs["betas"] = betas

        try:
            response = self.client.beta.messages.parse(**kwargs)
        except anthropic.BadRequestError as e:
            raise LLMError(f"Request rejected by the model API: {e.message}") from e
        except anthropic.AuthenticationError as e:
            raise LLMError("The model API key is missing or invalid.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("The model API is rate limiting requests. Try again shortly.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Model API error ({e.status_code}). Try again shortly.") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the model API.") from e

        usage = _cost(response.model or model, response.usage)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            reason = getattr(details, "explanation", None) or "the request was declined"
            raise LLMError(f"The model declined this request: {reason}")
        if response.stop_reason == "max_tokens":
            raise LLMError("The model ran out of output space. Ask for fewer ads per request.")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("The model returned output that did not match the expected format.")
        log.info(
            "llm call role=%s model=%s in=%d out=%d cost=$%.4f request_id=%s",
            role, usage.model, usage.tokens_in, usage.tokens_out, usage.cost_usd, response._request_id,
        )
        return LLMResult(parsed=parsed, usage=usage)


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = AnthropicLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    """Swap the LLM implementation (tests use a fake)."""
    global _llm
    _llm = llm
