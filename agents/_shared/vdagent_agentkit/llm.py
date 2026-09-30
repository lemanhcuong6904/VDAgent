"""Provider-agnostic structured LLM calls (D9, D10, build spec 00 §5).

Agents never parse free text from a model: `LlmRouter.structured(Model, messages)` asks for JSON matching the
Pydantic model's JSON Schema, validates it, makes one repair call with the validation errors, and tries the next
provider on transient / quota failures. Every attempt, failed or not, is reported in `usage` for cost accounting.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError


class LlmErrorCode(StrEnum):
    TRANSIENT = "TRANSIENT"  # one provider timed out / 5xx; the router tries the next one
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    INVALID_OUTPUT = "INVALID_OUTPUT"  # still not matching the schema after one repair
    UNAVAILABLE = "UNAVAILABLE"  # every provider failed transiently
    PROVIDER_ERROR = "PROVIDER_ERROR"  # the provider refused the request (bad params, auth, unknown model)


# Agent-level error codes declared in the catalogs (Data v02, Insight 2.0).
_AGENT_CODES = {
    LlmErrorCode.TRANSIENT: "LLM_UNAVAILABLE",
    LlmErrorCode.UNAVAILABLE: "LLM_UNAVAILABLE",
    LlmErrorCode.QUOTA_EXHAUSTED: "LLM_QUOTA_EXHAUSTED",
    LlmErrorCode.INVALID_OUTPUT: "LLM_INVALID_OUTPUT",
    LlmErrorCode.PROVIDER_ERROR: "LLM_UNAVAILABLE",
}


class LlmError(Exception):
    def __init__(self, code: LlmErrorCode, message: str, *, calls: int = 0, usage: list[LlmUsage] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.calls = calls
        self.usage: list[LlmUsage] = usage or []  # every attempt, for cost accounting

    @property
    def agent_code(self) -> str:
        return _AGENT_CODES[self.code]


@dataclass(frozen=True)
class LlmUsage:
    model: str
    prompt_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    finish_reason: str | None = None
    ok: bool = True


@dataclass(frozen=True)
class Completion:
    text: str
    usage: LlmUsage


class LLMClient(Protocol):
    model: str

    async def complete_json(
        self, messages: list[dict[str, Any]], schema: dict[str, Any], *, temperature: float
    ) -> Completion:
        """One call asking for a JSON object matching `schema`; raises LlmError(TRANSIENT | QUOTA_EXHAUSTED)."""
        ...


@dataclass
class CallBudget:
    """A cap on provider calls shared by every client of a router (e.g. `run.max_llm_calls`): failed calls count too."""

    limit: int
    used: int = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


class _BudgetedClient:
    def __init__(self, inner: LLMClient, budget: CallBudget) -> None:
        self.model = inner.model
        self._inner = inner
        self._budget = budget

    async def complete_json(
        self, messages: list[dict[str, Any]], schema: dict[str, Any], *, temperature: float
    ) -> Completion:
        if self._budget.exhausted:  # at the cap the model is treated as unavailable (Orchestrator INT-4)
            raise LlmError(LlmErrorCode.TRANSIENT, f"LLM call budget of {self._budget.limit} used up")
        self._budget.used += 1
        return await self._inner.complete_json(messages, schema, temperature=temperature)


@dataclass
class StructuredResult[T: BaseModel]:
    value: T
    calls: int
    usage: list[LlmUsage] = field(default_factory=list)


def _repair_message(problem: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": (
            "Your previous answer was invalid for the required JSON schema: "
            f"{problem[:1500]}\nReturn only a corrected JSON object."
        ),
    }


class LlmRouter:
    """Providers in preference order (primary, then fallbacks)."""

    def __init__(self, clients: Sequence[LLMClient]) -> None:
        if not clients:
            raise ValueError("at least one LLM client is required")
        self._clients = list(clients)

    def with_budget(self, budget: CallBudget) -> LlmRouter:
        """The same providers, each call counted against `budget`."""
        return LlmRouter([_BudgetedClient(c, budget) for c in self._clients])

    async def _complete(self, messages: list[dict[str, Any]], schema: dict[str, Any], temperature: float, usage: list[LlmUsage]) -> str:
        last: LlmError | None = None
        for client in self._clients:
            try:
                completion = await client.complete_json(messages, schema, temperature=temperature)
            except LlmError as exc:
                usage.append(LlmUsage(model=client.model, ok=False))
                last = exc
                continue
            usage.append(completion.usage)
            return completion.text
        assert last is not None
        if all(u.ok is False for u in usage[-len(self._clients):]) and last.code is LlmErrorCode.QUOTA_EXHAUSTED:
            raise LlmError(LlmErrorCode.QUOTA_EXHAUSTED, last.message, calls=len(usage))
        raise LlmError(LlmErrorCode.UNAVAILABLE, f"all providers failed; last: {last.message}", calls=len(usage))

    async def structured[T: BaseModel](
        self, model: type[T], messages: list[dict[str, Any]], *, temperature: float = 0.0
    ) -> StructuredResult[T]:
        schema = model.model_json_schema()
        usage: list[LlmUsage] = []
        conversation = list(messages)
        problem = ""
        for attempt in range(2):  # the call, then one repair
            try:
                text = await self._complete(conversation, schema, temperature, usage)
            except LlmError as exc:
                exc.calls, exc.usage = len(usage), list(usage)
                raise
            try:
                value = model.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as exc:
                problem = str(exc)
                if attempt == 0:
                    conversation = [*conversation, {"role": "assistant", "content": text}, _repair_message(problem)]
                continue
            return StructuredResult(value=value, calls=len(usage), usage=usage)
        raise LlmError(LlmErrorCode.INVALID_OUTPUT, problem[:500], calls=len(usage), usage=list(usage))


class LiteLLMClient:
    """OpenAI-compatible endpoint through LiteLLM; credentials passed explicitly (R11)."""

    def __init__(self, *, model: str, api_base: str, api_key: str, timeout_s: float,
                 reasoning_effort: str | None = None) -> None:
        self.model = model
        self._reasoning_effort = reasoning_effort  # e.g. "none": reasoning models accept temperature=0 only then
        self._api_base = api_base
        self._api_key = api_key
        self._timeout_s = timeout_s

    async def complete_json(
        self, messages: list[dict[str, Any]], schema: dict[str, Any], *, temperature: float
    ) -> Completion:
        import litellm  # heavy import, only when a real call happens

        kwargs: dict[str, Any] = {
            "model": f"openai/{self.model}",
            "api_base": self._api_base,
            "api_key": self._api_key,
            "timeout": self._timeout_s,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}},
        }
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        try:
            async with asyncio.timeout(self._timeout_s):
                response = await litellm.acompletion(**kwargs)
        except litellm.RateLimitError as exc:
            quota = "quota" in str(exc).lower() or "insufficient" in str(exc).lower()
            raise LlmError(LlmErrorCode.QUOTA_EXHAUSTED if quota else LlmErrorCode.TRANSIENT, str(exc)) from exc
        except (TimeoutError, litellm.Timeout, litellm.APIConnectionError, litellm.ServiceUnavailableError,
                litellm.InternalServerError) as exc:
            raise LlmError(LlmErrorCode.TRANSIENT, str(exc) or type(exc).__name__) from exc
        except (litellm.UnsupportedParamsError, litellm.BadRequestError, litellm.AuthenticationError,
                litellm.NotFoundError, litellm.APIError) as exc:  # never let a provider refusal crash the turn
            raise LlmError(LlmErrorCode.PROVIDER_ERROR, str(exc) or type(exc).__name__) from exc
        choice = response.choices[0]
        raw_usage = getattr(response, "usage", None)
        details = getattr(raw_usage, "prompt_tokens_details", None)
        completion_details = getattr(raw_usage, "completion_tokens_details", None)
        usage = LlmUsage(
            model=self.model,
            prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
            cached_tokens=int(getattr(details, "cached_tokens", 0) or 0),
            output_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
            reasoning_tokens=int(getattr(completion_details, "reasoning_tokens", 0) or 0),
            finish_reason=getattr(choice, "finish_reason", None),
        )
        return Completion(text=choice.message.content or "", usage=usage)
