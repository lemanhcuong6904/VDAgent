"""Treat artifact text as data and remove unsafe display content."""

from __future__ import annotations
import re

_HTML = re.compile(r"<[^>]*>")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_INSTRUCTION = re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I)


def sanitize_text(value: str) -> str:
    clean = _EMAIL.sub("[redacted]", _HTML.sub("", value)).strip()
    return "[redacted]" if _INSTRUCTION.search(clean) else clean
