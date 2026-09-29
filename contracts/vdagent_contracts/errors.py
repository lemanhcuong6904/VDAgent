"""The ten error classes the Orchestrator acts on (build spec 00 §3.1). Codes map to classes in each catalog."""

from __future__ import annotations

from enum import StrEnum


class ErrorClass(StrEnum):
    NEED_INPUT = "NEED_INPUT"
    WRONG_RESULT = "WRONG_RESULT"
    SPEC_ISSUE = "SPEC_ISSUE"
    NO_DATA = "NO_DATA"
    NO_ACCESS = "NO_ACCESS"
    DATA_QUALITY = "DATA_QUALITY"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TRANSIENT = "TRANSIENT"
    FATAL = "FATAL"
    CANCELED = "CANCELED"
