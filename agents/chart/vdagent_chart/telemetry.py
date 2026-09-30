"""Structured Chart Agent telemetry with deliberately non-sensitive fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
import re


_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|prompt|record|dataset|payload|text|message)", re.I)
_SENSITIVE_VALUE = re.compile(r"(?:\bsk-[A-Za-z0-9_-]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})")


def safe_attributes(attributes: Mapping[str, str | int | bool]) -> dict[str, str | int | bool]:
    """Keep telemetry structural: never retain prompts, records, PII, or keys."""
    safe: dict[str, str | int | bool] = {}
    for key, value in attributes.items():
        if _SENSITIVE_KEY.search(key):
            continue
        if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
            continue
        safe[key] = value
    return safe


@dataclass(frozen=True)
class ChartEvent:
    name: str
    attributes: Mapping[str, str | int | bool]


class TelemetryPort(Protocol):
    def record(self, name: str, attributes: Mapping[str, str | int | bool]) -> None: ...


class InMemoryTelemetry:
    """Demo/test collector. Production adapters can forward the same safe envelope."""

    def __init__(self) -> None:
        self.events: list[ChartEvent] = []

    def record(self, name: str, attributes: Mapping[str, str | int | bool]) -> None:
        self.events.append(ChartEvent(name, safe_attributes(attributes)))
