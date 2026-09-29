"""SIMPLE_ROUTER (build spec 01 §4.2 INT-4): when LLM 1 is unavailable, only plain LOOKUP questions are served."""

from __future__ import annotations

import re
import unicodedata

from vdagent_contracts.intents import TaskKind
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.intent import IntentDraft

NUMBER_WORDS = ("bao nhieu", "trung binh", "tong so", "ty le", "so can", "cao nhat", "thap nhat")
DECISION_WORDS = ("nen", "quyet dinh", "de xuat")


def normalize(text: str) -> str:
    """No diacritics, lower case, single spaces, punctuation dropped (matching only, never shown)."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().replace("_", " ")
    return " ".join(re.sub(r"[^\w\s-]", " ", stripped).split())


def _has(words: str, phrase: str) -> bool:
    return f" {phrase} " in f" {words} "


def route(question: str, registry: CatalogRegistry) -> IntentDraft | None:
    """A number word and one Data metric (by name or by the label before ':' / '(' in its description), and no
    decision word → LOOKUP over the user's whole scope; anything else → None (the caller answers LLM_UNAVAILABLE)."""
    words = normalize(question)
    if not any(_has(words, w) for w in NUMBER_WORDS) or any(_has(words, w) for w in DECISION_WORDS):
        return None
    matches: list[tuple[int, str]] = []
    for metric in registry.catalogs["data"].vocabulary.metrics:
        label = normalize(re.split(r"[:(]", metric.description)[0])
        for phrase in (normalize(metric.name), label):
            if phrase and _has(words, phrase):
                matches.append((len(phrase), metric.name))
    if not matches:
        return None
    best = max(matches)[1]
    return IntentDraft(scope_check="ANALYSIS", task_kinds=[TaskKind.LOOKUP], metrics=[best], scope_all=True)


__all__ = ["normalize", "route"]
