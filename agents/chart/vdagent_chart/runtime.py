"""Small deterministic runtime contracts used by the fixture-backed agent."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


def canonical_input_hash(material: object) -> str:
    """Create an order-independent content address for idempotency material."""
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChartRunState:
    input_hash: str
    status: str = "queued"

    @classmethod
    def new(cls, input_hash: str) -> "ChartRunState":
        return cls(input_hash=input_hash)

    def start(self) -> "ChartRunState":
        if self.status in {"completed", "failed"}:
            raise ValueError("terminal chart run cannot transition to running")
        return ChartRunState(self.input_hash, "running")

    def complete(self) -> "ChartRunState":
        if self.status != "running":
            raise ValueError("only a running chart run can complete")
        return ChartRunState(self.input_hash, "completed")

    def fail(self) -> "ChartRunState":
        if self.status != "running":
            raise ValueError("only a running chart run can fail")
        return ChartRunState(self.input_hash, "failed")
