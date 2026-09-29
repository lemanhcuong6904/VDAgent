"""LLM 2 (build spec 01 §6.2 PLN-1): IntentFrame + catalogs → PlanDraft. Never sees `user_context` or package contents."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vdagent_agentkit.llm import LlmError, LlmRouter, LlmUsage
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.intent import IntentFrame
from vdagent_orchestrator.planning import PlanDraft

PROMPT_VERSION = "orchestrator-plan-1.0.0"
PROMPTS_DIR = Path(__file__).parent / "prompts"
FRAME_FIELDS = ("task_kinds", "mentions", "scope_all", "metrics", "dimensions", "filters", "phenomena", "unmatched_needs",
                "requested_outputs", "uncovered_task_kinds")


@dataclass
class DraftOutcome:
    draft: PlanDraft | None
    llm_calls: int = 0
    usage: list[LlmUsage] = field(default_factory=list)
    error: str | None = None  # agent-level LLM code when draft is None


def _catalog_brief(registry: CatalogRegistry) -> str:
    lines = []
    for agent, catalog in sorted(registry.catalogs.items()):
        for op in catalog.operations:
            lines.append(json.dumps({"agent": agent, "operation": op.operation, "description": op.description,
                                     "requires": op.requires, "uses_if_present": op.uses_if_present, "produces": op.produces,
                                     "outputs": [o.value for o in op.outputs], "serves": [s.value for s in op.serves],
                                     "input_schema": op.input_schema}, ensure_ascii=False))
    return "\n".join(lines)


def messages_for(frame: IntentFrame, registry: CatalogRegistry, *, extra: dict[str, Any] | None = None,
                 previous: PlanDraft | None = None, violations: Sequence[str] = ()) -> list[dict[str, str]]:
    system = (f"[{PROMPT_VERSION}]\n" + (PROMPTS_DIR / "plan.md").read_text(encoding="utf-8").strip()
              + "\n\nDanh mục (mỗi dòng một operation):\n" + _catalog_brief(registry))
    data: dict[str, Any] = {"question": frame.original_question,
                            "intent_frame": frame.model_dump(mode="json", include=set(FRAME_FIELDS)), **(extra or {})}
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": f"<data>\n{body}\n</data>"}]
    if violations:
        if previous is not None:
            messages.append({"role": "assistant", "content": previous.model_dump_json()})
        messages.append({"role": "user", "content": "Kế hoạch trước vi phạm các luật sau, hãy sửa và trả lại toàn bộ JSON:\n"
                                                    + "\n".join(f"- {v}" for v in violations)})
    return messages


async def draft_plan(frame: IntentFrame, *, router: LlmRouter | None, registry: CatalogRegistry,
                     extra: dict[str, Any] | None = None, previous: PlanDraft | None = None,
                     violations: Sequence[str] = ()) -> DraftOutcome:
    if router is None:
        return DraftOutcome(None, error="LLM_UNAVAILABLE")
    try:
        result = await router.structured(PlanDraft, messages_for(frame, registry, extra=extra, previous=previous,
                                                                violations=violations))
    except LlmError as exc:
        return DraftOutcome(None, llm_calls=exc.calls, usage=exc.usage, error=exc.agent_code)
    return DraftOutcome(result.value, llm_calls=result.calls, usage=result.usage)


__all__ = ["PROMPT_VERSION", "DraftOutcome", "draft_plan", "messages_for"]
