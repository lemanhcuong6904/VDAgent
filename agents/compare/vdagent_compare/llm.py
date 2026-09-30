"""Model access for Compare: one JSON-shaped completion per call, never a tool loop (spec §1.9).

The model fills a JSON schema (a comparison plan, or the wording of an answer). Code checks
every reply before use; the model never calls tools and never produces a number on its own.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from typing import Any, Protocol

log = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Every configured model failed (timeout, quota, network, malformed reply)."""


class JsonLLM(Protocol):
    async def complete_json(self, messages: list[dict[str, Any]], *, name: str, schema: dict) -> dict:
        """One completion constrained to `schema`; raises `LLMUnavailableError` when no model answers."""
        ...


class LiteLLMJsonClient:
    """`litellm.acompletion` against an OpenAI-compatible endpoint, trying `models` in order.

    Structured output (`json_schema`, strict) keeps replies parseable; a model that rejects it is
    retried once with plain JSON mode before moving on to the next model.
    """

    def __init__(self, *, models: Sequence[str], api_base: str, api_key: str, timeout_s: float) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self._models = tuple(models)
        self._api_base = api_base
        self._api_key = api_key
        self._timeout_s = timeout_s

    @property
    def models(self) -> tuple[str, ...]:
        return self._models

    async def complete_json(self, messages: list[dict[str, Any]], *, name: str, schema: dict) -> dict:
        import litellm  # heavy import; only when a model is actually configured

        strict = {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}
        errors: list[str] = []
        for model in self._models:
            for response_format in (strict, {"type": "json_object"}):
                try:
                    async with asyncio.timeout(self._timeout_s):  # also bounds LiteLLM's own retries
                        response = await litellm.acompletion(
                            model=f"openai/{model}", api_base=self._api_base, api_key=self._api_key,
                            timeout=self._timeout_s, messages=messages, response_format=response_format,
                        )
                    content = response.choices[0].message.content or ""
                    reply = json.loads(content)
                    if not isinstance(reply, dict):
                        raise ValueError("reply is not a JSON object")
                    return reply
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — any failure moves on; the caller has a fallback
                    errors.append(f"{model}/{response_format['type']}: {type(exc).__name__}: {exc}"[:300])
                    log.warning("compare LLM %s failed for %s: %s", model, name, errors[-1])
                    if not _format_rejected(exc):
                        break  # plain JSON mode will not fix a timeout or a quota error; try the next model
        raise LLMUnavailableError("; ".join(errors))


def _format_rejected(exc: Exception) -> bool:
    text = str(exc).lower()
    return "response_format" in text or "json_schema" in text or "structured" in text
