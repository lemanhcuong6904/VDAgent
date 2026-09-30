"""Canonical JSON, content hashing and Decimal helpers (system prompt §4 rules 5–6).

`content_hash` is the SHA-256 of the canonical JSON of an object without its run-identity fields, so the same
input + config + code gives the same hash across runs. Money, ratios and percentages are `Decimal` end to end:
a `float` anywhere in a hashed payload is a bug and raises.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

# Fields that identify one run of an artifact rather than its content; dropped at every nesting level.
RUN_IDENTITY_FIELDS = frozenset(
    {
        "artifact_id", "run_id", "task_id", "version", "input_artifact_refs", "created_at", "content_hash",
        "idempotency_key", "plan_id",  # a plan's identity changes every run (R-03)
    }
)

_CENT = Decimal("0.01")


def _normalize(value: Any, *, strip: bool) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"canonical JSON keys must be strings, got {type(key).__name__}")
            if strip and key in RUN_IDENTITY_FIELDS:
                continue
            out[key] = _normalize(item, strip=strip)
        return out
    if isinstance(value, (str, bool, int)) or value is None:
        return value
    if isinstance(value, float):
        raise TypeError("float in canonical payload: use Decimal")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _normalize(value.value, strip=strip)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_normalize(item, strip=strip) for item in value]
    raise TypeError(f"unsupported type in canonical payload: {type(value).__name__}")


def canonical_json(obj: Any) -> str:
    """Sorted keys, no spaces, UTF-8 kept, Decimal as string. Keeps every field."""
    return json.dumps(_normalize(obj, strip=False), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj: Any) -> str:
    """SHA-256 hex of the canonical JSON of `obj` without run-identity fields."""
    text = json.dumps(_normalize(obj, strip=True), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def q2(value: Decimal) -> Decimal:
    """Round to 2 decimals, half away from zero (the storage rounding)."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def percentile_inc(values: Sequence[Decimal], p: Decimal) -> Decimal:
    """PERCENTILE.INC: linear interpolation at rank 1 + p·(n−1) of the sorted values."""
    if not values:
        raise ValueError("percentile of an empty sample")
    if not Decimal(0) <= p <= Decimal(1):
        raise ValueError("p must be within [0, 1]")
    ordered = sorted(values)
    position = p * (len(ordered) - 1)
    low = int(position)
    fraction = position - low
    if low + 1 >= len(ordered):
        return ordered[low]
    return ordered[low] + (ordered[low + 1] - ordered[low]) * fraction
