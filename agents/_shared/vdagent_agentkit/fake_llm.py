"""Scripted LLM for tests (D11): never touches the network."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vdagent_agentkit.llm import Completion, LlmError, LlmUsage

Step = str | LlmError | Callable[[list[dict[str, Any]], dict[str, Any]], str]


class FakeLLM:
    """Replays `script` one step per call: a JSON text, an LlmError to raise, or a function of (messages, schema)."""

    def __init__(self, script: list[Step], *, model: str = "fake-model", usage: LlmUsage | None = None) -> None:
        self.model = model
        self._script = list(script)
        self._usage = usage
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self, messages: list[dict[str, Any]], schema: dict[str, Any], *, temperature: float
    ) -> Completion:
        self.calls.append({"messages": list(messages), "schema": schema, "temperature": temperature})
        assert self._script, f"FakeLLM {self.model}: script exhausted after {len(self.calls) - 1} calls"
        step = self._script.pop(0)
        if isinstance(step, LlmError):
            raise step
        text = step(messages, schema) if callable(step) else step
        return Completion(text=text, usage=self._usage or LlmUsage(model=self.model))

    @property
    def remaining(self) -> int:
        return len(self._script)
