"""LLM 1 (build spec 01 §4.2 INT-1…INT-4): question → IntentDraft.

UI selections are turned into a draft by code (INT-1). The model sees the question inside a data block and the Data
catalog names — never `user_context`, thresholds or package contents (INT-2). Names outside the vocabulary and mentions
the user never wrote are dropped after parsing (INT-3, injection guard). Without a usable LLM, SIMPLE_ROUTER (INT-4).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from vdagent_agentkit.llm import LlmError, LlmRouter, LlmUsage
from vdagent_contracts.intents import OutputKind, TaskKind
from vdagent_orchestrator import simple_router
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.intent import IntentDraft, IntentFrame, Mention

PROMPT_VERSION = "orchestrator-intent-1.0.0"
PROMPTS_DIR = Path(__file__).parent / "prompts"
# OPEN(Q-04): the UI button mapping is a placeholder until the UI spec lands
UI_BUTTONS: dict[str, tuple[list[TaskKind], list[OutputKind]]] = {
    "Xuất báo cáo": ([TaskKind.EXPLAIN], [OutputKind.CHAT_ANSWER, OutputKind.CHART, OutputKind.REPORT]),
    "Giải thích": ([TaskKind.EXPLAIN], [OutputKind.CHAT_ANSWER]),
}

Source = Literal["UI_SELECTION", "LLM", "SIMPLE_ROUTER", "FAILED"]


@dataclass
class Understanding:
    draft: IntentDraft | None
    source: Source
    llm_calls: int = 0
    usage: list[LlmUsage] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # names / mentions removed by the sanitizer


def _catalog_brief(registry: CatalogRegistry) -> str:
    vocab = registry.catalogs["data"].vocabulary
    return "\n".join([
        "Metric: " + "; ".join(f"{v.name} ({v.description})" for v in vocab.metrics),
        "Dimension: " + "; ".join(f"{v.name} ({v.description})" for v in vocab.dimensions),
        "Filter: " + "; ".join(f"{v.name} ({v.description})" for v in vocab.filters),
        "Loại câu hỏi hệ thống phục vụ: " + ", ".join(sorted(k.value for k in registry.served_kinds())),
    ])


def messages_for(question: str, registry: CatalogRegistry, *, clarify_answers: Sequence[str] = (),
                 parent_frame: IntentFrame | None = None) -> list[dict[str, str]]:
    system = (f"[{PROMPT_VERSION}]\n" + (PROMPTS_DIR / "intent.md").read_text(encoding="utf-8").strip()
              + "\n\nDanh mục:\n" + _catalog_brief(registry))
    data: dict[str, Any] = {"question": question, "clarify_answers": list(clarify_answers)}
    if parent_frame is not None:
        data["previous_turn"] = {"task_kinds": [k.value for k in parent_frame.task_kinds],
                                 "mentions": [m.text for m in parent_frame.mentions], "metrics": parent_frame.metrics}
    # the user's text can never open or close the data block
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    return [{"role": "system", "content": system}, {"role": "user", "content": f"<data>\n{body}\n</data>"}]


def sanitize(draft: IntentDraft, said: Sequence[str], registry: CatalogRegistry) -> tuple[IntentDraft, list[str]]:
    vocab = registry.vocabulary()
    words = " " + simple_router.normalize(" ".join(said)) + " "
    dropped: list[str] = []

    def keep(values: list[str], allowed: list[str]) -> list[str]:
        dropped.extend(v for v in values if v not in allowed)
        return [v for v in values if v in allowed]

    mentions: list[Mention] = []
    for mention in draft.mentions:
        if f" {simple_router.normalize(mention.text)} " in words:
            mentions.append(mention)
        else:
            dropped.append(mention.text)
    clean = draft.model_copy(update={
        "metrics": keep(draft.metrics, vocab["metrics"]), "dimensions": keep(draft.dimensions, vocab["dimensions"]),
        "filters": keep(draft.filters, vocab["filters"]), "mentions": mentions,
    })
    return clean, dropped


def _from_ui(selection: dict[str, Any]) -> IntentDraft:
    kinds, outputs = UI_BUTTONS.get(str(selection.get("button", "")), ([TaskKind.EXPLAIN], [OutputKind.CHAT_ANSWER]))
    mentions = [Mention.model_validate(m) for m in selection.get("mentions", [])]
    return IntentDraft(scope_check="ANALYSIS", task_kinds=kinds, mentions=mentions, requested_outputs=outputs,
                       phenomena=["bán chậm"] if TaskKind.EXPLAIN in kinds else [])


def _fallback(question: str, registry: CatalogRegistry, calls: int = 0, usage: list[LlmUsage] | None = None) -> Understanding:
    draft = simple_router.route(question, registry)
    return Understanding(draft, "SIMPLE_ROUTER" if draft else "FAILED", llm_calls=calls, usage=usage or [])


async def understand(question: str, *, router: LlmRouter | None, registry: CatalogRegistry, clarify_answers: Sequence[str] = (),
                     parent_frame: IntentFrame | None = None, ui_selection: dict[str, Any] | None = None) -> Understanding:
    if ui_selection is not None:
        return Understanding(_from_ui(ui_selection), "UI_SELECTION")
    if router is None:
        return _fallback(question, registry)
    try:
        result = await router.structured(IntentDraft, messages_for(question, registry, clarify_answers=clarify_answers,
                                                                   parent_frame=parent_frame))
    except LlmError as exc:  # still invalid after the repair, quota, or every provider down
        return _fallback(question, registry, exc.calls, exc.usage)
    said = [question, *clarify_answers, *([m.text for m in parent_frame.mentions] if parent_frame else [])]
    draft, dropped = sanitize(result.value, said, registry)
    return Understanding(draft, "LLM", llm_calls=result.calls, usage=result.usage, dropped=dropped)


__all__ = ["PROMPT_VERSION", "Understanding", "messages_for", "sanitize", "understand"]
