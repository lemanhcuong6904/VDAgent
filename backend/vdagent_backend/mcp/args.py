"""Tool argument parsers: each returns the cleaned value or raises `ToolError` with the model-facing text."""

from __future__ import annotations

from typing import Any


class ToolError(Exception):
    """A user-facing tool failure; its message becomes the tool error text."""


def required_str(args: dict[str, Any], key: str) -> str:
    """A non-empty string, stripped."""
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' is required and must be a non-empty string")
    return value.strip()


def optional_str(args: dict[str, Any], key: str) -> str | None:
    """A string, stripped; None when missing or blank."""
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"'{key}' must be a string")
    return value.strip() or None


def bounded_int(args: dict[str, Any], key: str, default: int, low: int, high: int | None = None) -> int:
    """An integer in `[low, high]` (integral floats accepted); `default` when missing."""
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"'{key}' must be an integer")
    if value < low or (high is not None and value > high):
        bounds = f"between {low} and {high}" if high is not None else f">= {low}"
        raise ToolError(f"'{key}' must be {bounds}")
    return value


def str_list(args: dict[str, Any], key: str) -> list[str]:
    """A non-empty list of non-empty strings, each stripped."""
    value = args.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise ToolError(f"'{key}' must be a non-empty array of strings")
    return [v.strip() for v in value]
