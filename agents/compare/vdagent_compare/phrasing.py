"""Engine result → a short Vietnamese answer written by the model, checked by code (spec §1.9, R5, R14).

The model only sees the engine's rendered result and must reuse its numbers. `check_phrase`
rejects any number absent from that result (`numbersMatch`), any causal wording and any
recommendation. One rewrite is allowed; after that the caller keeps the template text.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .llm import JsonLLM

PROMPT = (Path(__file__).parent / "prompts" / "phrase.md").read_text(encoding="utf-8").strip()
ANSWER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text"],
                 "properties": {"text": {"type": "string"}}}
MAX_CHARS = 900

# Codes and labels whose digits are not quantities: A12-08, SAPPHIRE1-13.001, SNAP-20260630-01, 2PN, m².
_NOT_QUANTITIES = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-.][A-Z0-9]+)+\b|\b\dPN\b|\bm[2²]", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_THOUSANDS = re.compile(r"^\d{1,3}(?:\.\d{3})+(?:,\d+)?$")
_FORBIDDEN = re.compile(
    r"(?<!\w)(vì|do|bởi|khiến|dẫn đến|nguyên nhân|nên|hãy|khuyến nghị|đề xuất|cần phải"
    r"|đắt|rẻ|tốt hơn|xấu hơn)(?!\w)",  # last four: a price is only "cao hơn"/"thấp hơn", never good or bad
    re.IGNORECASE)


def _value(token: str) -> Decimal | None:
    text = token.replace(".", "").replace(",", ".") if _THOUSANDS.match(token) else token.replace(",", ".")
    try:
        return Decimal(text).normalize()
    except InvalidOperation:
        return None  # e.g. a version like 3.1.0: not a quantity


def numbers_in(text: str) -> set[Decimal]:
    cleaned = _NOT_QUANTITIES.sub(" ", text)
    return {v for token in _NUMBER.findall(cleaned) if (v := _value(token)) is not None}


def check_phrase(text: str, facts: str) -> list[str]:
    """Problems with a model-written answer; empty means it may be published."""
    problems = []
    unknown = sorted(numbers_in(text) - numbers_in(facts))
    if unknown:
        problems.append("có số không nằm trong kết quả: " + ", ".join(format(v, "f") for v in unknown))
    words = sorted({m.group(1).lower() for m in _FORBIDDEN.finditer(text)})
    if words:
        problems.append("có từ nhân quả hoặc khuyến nghị: " + ", ".join(words))
    if not text.strip():
        problems.append("câu trả lời rỗng")
    if len(text) > MAX_CHARS:
        problems.append(f"dài quá {MAX_CHARS} ký tự")
    return problems


def facts_from(rendered: str) -> str:
    """The rendered result without the evidence line (ids and hashes are not facts to cite)."""
    return "\n".join(line for line in rendered.splitlines() if not line.startswith("Chứng cứ:"))


async def phrase(llm: JsonLLM, question: str, facts: str) -> str | None:
    """A checked answer, or `None` when two attempts fail the check. `LLMUnavailableError` propagates."""
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"Câu hỏi của người dùng:\n{question}\n\nKết quả của engine "
                                    f"(nguồn số liệu duy nhất):\n{facts}"},
    ]
    for attempt in range(2):
        reply = await llm.complete_json(messages, name="comparison_answer", schema=ANSWER_SCHEMA)
        text = str(reply.get("text") or "").strip()
        problems = check_phrase(text, facts)
        if not problems:
            return text
        if attempt == 0:
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "Bản trên không dùng được vì " + "; ".join(problems)
                                                     + ". Viết lại, chỉ dùng số có trong kết quả, chỉ mô tả."}]
    return None
