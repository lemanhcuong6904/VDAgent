"""The narrator: turns the real trace of a Data step into natural language for the person watching.

Nothing about a result is written in advance. The events (`trace.py`) carry the facts of the run; a `Narrator` says them:

* `TemplateNarrator` builds each sentence from the facts (deterministic, free, works with `DATA_LLM=off`).
* `LlmNarrator` lets an LLM rewrite that draft in the words of the task, but only what the facts support: every number and
  identifier in its sentence must be found in the facts, else the template sentence is used. It sees metadata only
  (tables, row counts, codes, the original question), never row values (SPEC §3.5).

`group_beats` cuts the trace into one beat per pipeline phase; `NarrationStream` is the observer that narrates the beats
in the background while the step keeps working, and hands each one to a sink (the agent turns it into an SDK step).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from vdagent_sdk import ToolCall

from .llm import LLMClient
from .trace import TraceEvent

log = logging.getLogger(__name__)

MAX_SENTENCE_CHARS = 700
DEFAULT_LLM_TIMEOUT_S = 10.0
MAX_PURPOSES = 4  # purposes quoted in one beat; the rest are counted


@dataclass(frozen=True)
class Task:
    """What the step was asked to do; taken from the trace's own `intake` event."""

    operation: str
    question: str


@dataclass(frozen=True)
class Beat:
    """The events of one pipeline phase, told as one step."""

    phase: str
    events: tuple[TraceEvent, ...]


class Narrator(Protocol):
    async def narrate(self, beat: Beat, task: Task) -> str: ...


def group_beats(events: Sequence[TraceEvent]) -> list[Beat]:
    """One beat per run of consecutive events of the same phase."""
    beats: list[Beat] = []
    current: list[TraceEvent] = []
    for event in events:
        if current and event.phase != current[-1].phase:
            beats.append(Beat(current[0].phase, tuple(current)))
            current = []
        current.append(event)
    if current:
        beats.append(Beat(current[0].phase, tuple(current)))
    return beats


# ---- the real tool calls of a beat ------------------------------------------------------------------------------------


def tool_calls_of(beat: Beat) -> list[tuple[ToolCall, str]]:
    """Each warehouse or artifact-store call of the beat as an SDK `ToolCall` with its (summarised) result."""
    starts = {e.call_id: e for e in beat.events if e.state == "start"}
    out: list[tuple[ToolCall, str]] = []
    for end in (e for e in beat.events if e.state == "end" and e.call_id in starts):
        start = starts[end.call_id]
        tool = str(start.facts.get("tool") or start.stage)
        args = {k: v for k, v in start.facts.items() if k != "tool"} | {"purpose": start.purpose}
        call = ToolCall(id=str(end.call_id), name=tool, arguments_json=json.dumps(args, ensure_ascii=False))
        if "error" in end.facts:
            result = f"error: {end.facts['error']}"
        else:
            result = json.dumps({k: v for k, v in end.facts.items() if k not in ("table", "artifact_type")}, ensure_ascii=False)
        out.append((call, result))
    return out


# ---- fact check -------------------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_@#.\-]*[_@#][A-Za-z0-9_@#.\-]*")
_HASH = re.compile(r"\b[0-9a-f]{16,}\b")


def _digits(token: str) -> str:
    return re.sub(r"[.,]", "", token)


def _plain_numbers(text: str) -> list[str]:
    """The numbers of `text` outside identifiers and hashes (the digits inside `art_004a…` or a sha256 are not figures)."""
    return _NUMBER.findall(_IDENTIFIER.sub(" ", _HASH.sub(" ", text)))


def numbers_supported(text: str, sources: Iterable[str]) -> bool:
    """True when every number and every identifier (a token with `_`, `@` or `#`) in `text` occurs in `sources`.

    Numbers compare without thousand or decimal separators (3.260 = 3260), so a sentence may format a fact but never add one.
    The digits inside identifiers and hashes never count as figures, in the text or in the sources.
    """
    blob = "\n".join(sources)
    allowed = {_digits(t) for t in _plain_numbers(blob)}
    if any(_digits(t) not in allowed for t in _plain_numbers(text)):
        return False
    for identifier in _IDENTIFIER.findall(text):
        for part in re.split(r"[@#]", identifier.strip(".,;:-")):
            if part and part not in blob:
                return False
    return True


def sources_of(beat: Beat, task: Task, extra: str = "") -> list[str]:
    facts = [str(v) for e in beat.events for v in e.facts.values()]
    keys = [k for e in beat.events for k in e.facts]  # a sentence may name a field ("subject_unit_code")
    return [*facts, *keys, *(e.purpose for e in beat.events), task.question, task.operation, extra]


# ---- the template narrator --------------------------------------------------------------------------------------------


def _n(value: Any) -> str:
    return f"{value:,}".replace(",", ".") if isinstance(value, int) and not isinstance(value, bool) else str(value)


def _list(values: Any) -> str:
    return ", ".join(str(v) for v in values) if isinstance(values, list) and values else ""


def _purposes(events: Iterable[TraceEvent]) -> str:
    seen: list[str] = []
    for e in events:
        if e.purpose and e.purpose not in seen:
            seen.append(e.purpose)
    if not seen:
        return ""
    shown = "; ".join(seen[:MAX_PURPOSES])
    more = "; và các việc còn lại" if len(seen) > MAX_PURPOSES else ""  # no invented count: every figure must be a fact
    return f" Mục đích: {shown}{more}."


class TemplateNarrator:
    """First person, Vietnamese, every figure taken from the events of the beat."""

    async def narrate(self, beat: Beat, task: Task) -> str:
        parts = [self._reads(beat), *(self._note(e, task) for e in beat.events if e.state == "note"), self._writes(beat)]
        return " ".join(p for p in parts if p).strip()

    @staticmethod
    def _reads(beat: Beat) -> str:
        ends = [e for e in beat.events if e.state == "end" and e.stage == "read"]
        if not ends:
            return ""
        ok = [e for e in ends if "error" not in e.facts]
        failed = [e for e in ends if "error" in e.facts]
        text = ""
        if ok:
            rows: dict[str, list[str]] = {}
            for e in ok:  # a table read twice (the subject, then its candidates) is named once
                rows.setdefault(str(e.facts["table"]), []).append(f"{_n(e.facts['rows'])} dòng")
            text = "Đã đọc " + ", ".join(f"{table} ({' và '.join(counts)})" for table, counts in rows.items()) + "."
        if failed:
            text += " " + " ".join(f"Không đọc được {e.facts['table']}: {e.facts['error']}." for e in failed)
        return text.strip() + _purposes(e for e in beat.events if e.stage == "read" and e.state == "start")

    @staticmethod
    def _writes(beat: Beat) -> str:
        ends = [e for e in beat.events if e.state == "end" and e.stage == "write"]
        if not ends:
            return ""
        lines = []
        for e in ends:
            f = e.facts
            if "error" in f:
                lines.append(f"Không lưu được {f['artifact_type']}: {f['error']}.")
            else:
                codes = _list(f.get("limitation_codes"))
                lines.append(f"Đã lưu {f['artifact_type']} {f['artifact_id']}@{f['version']} ({f['status']}, {_n(f['size_bytes'])} byte"
                             + (f", hạn chế: {codes}" if codes else "") + ").")
        return " ".join(lines) + _purposes(e for e in beat.events if e.stage == "write" and e.state == "start")

    @staticmethod
    def _note(e: TraceEvent, task: Task) -> str:
        f = e.facts
        if e.stage == "intake":
            spec = ", ".join(f"{k.removeprefix('spec_')} = {_list(v) if isinstance(v, list) else v}"
                             for k, v in f.items() if k.startswith("spec_"))
            snapshot = (f"Kỳ chốt được yêu cầu: {f['snapshot_id']}"
                        + (f" (cấu hình {f['semantic_config_version']})" if f.get("semantic_config_version") else "")
                        if f.get("snapshot_id") else "Phiếu chưa nêu kỳ chốt")
            return (f"Mình nhận việc {f['operation']} từ Orchestrator cho câu hỏi “{f['original_question']}”"
                    + (f" ({spec})" if spec else "") + f". {snapshot}.")
        if e.stage == "scope":
            zones = _list(f.get("zone_ids"))
            projects = _list(f.get("project_ids"))
            return ("Quyền của người dùng lấy từ Backend, không lấy từ phiếu: "
                    + (f"dự án {projects}" if projects else "chưa có dự án nào") + (f"; phân khu {zones}" if zones else "") + ".")
        if e.stage == "snapshot":
            return (f"Đã ghim kỳ chốt {f['snapshot_id']} (ngày {f['snapshot_date']}, cấu hình {f['semantic_config_version']}) cho cả bước.")
        if e.stage == "config":
            said = [f"đã duyệt: {_list(f.get('approved'))}" if f.get("approved") else "",
                    f"chưa duyệt: {_list(f.get('pending'))}" if f.get("pending") else "",
                    f"không có trong kho: {_list(f.get('missing'))}" if f.get("missing") else ""]
            return "Ngưỡng nghiệp vụ " + ("; ".join(s for s in said if s) or "không có") + "; ngưỡng thiếu không được thay bằng giá trị mặc định."
        if e.stage == "check":
            limits = _list(f.get("limitations"))
            return (f"Kiểm tra chất lượng: trạng thái {f['overall_status']}, {f['fields_checked']} trường đã kiểm; "
                    + (f"hạn chế: {limits}." if limits else "không phát hiện hạn chế."))
        if e.stage == "done":
            return (f"Xong: đã lưu {f['artifacts']} gói kết quả"
                    + (f", có {f['warnings']} cảnh báo" if f.get("warnings") else "")
                    + (", kết quả một phần vì còn dữ liệu thiếu" if f.get("partial") else "") + ", báo lại cho Orchestrator.")
        if e.stage == "fail":
            return f"Không hoàn thành: {f['code']} ({f['state']}); không gói nào được coi là kết quả."
        return e.purpose


# ---- the LLM narrator -------------------------------------------------------------------------------------------------


class LlmNarrator:
    """Rewrites the template draft in the words of the task; anything the facts do not support returns the draft."""

    def __init__(self, llm: LLMClient, fallback: Narrator, *, timeout_s: float = DEFAULT_LLM_TIMEOUT_S, system_prompt: str = "") -> None:
        self._llm, self._fallback, self._timeout_s, self._system_prompt = llm, fallback, timeout_s, system_prompt

    async def narrate(self, beat: Beat, task: Task) -> str:
        draft = await self._fallback.narrate(beat, task)
        prompt = {
            "nhiem_vu": {"operation": task.operation, "cau_hoi_goc": task.question},
            "giai_doan": beat.phase,
            "ban_nhap": draft,
            "su_kien": [{"stage": e.stage, "state": e.state, "purpose": e.purpose, "facts": dict(e.facts)} for e in beat.events],
        }
        messages = [{"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]
        try:
            async with asyncio.timeout(self._timeout_s):
                reply = await self._llm.complete(messages, [], "none")
        except Exception as exc:  # timeout, provider error, anything: the draft is always a true answer
            log.info("data: the LLM narrator failed (%s); using the template", type(exc).__name__)
            return draft
        text = (reply.content or "").strip()
        if self._acceptable(text, beat, task, draft):
            return text
        log.info("data: the LLM narration was rejected (facts not supported); using the template")
        return draft

    @staticmethod
    def _acceptable(text: str, beat: Beat, task: Task, draft: str) -> bool:
        if not text or len(text) > MAX_SENTENCE_CHARS or "```" in text:
            return False
        return numbers_supported(text, sources_of(beat, task, draft))


# ---- the stream: narrates in the background while the step works ------------------------------------------------------


class StepSink(Protocol):
    async def step(self, text: str, calls: list[tuple[ToolCall, str]]) -> None:
        """Show one narrated step with the real tool calls of its phase and their results."""
        ...


class NarrationStream:
    """A trace observer: cuts the events into beats and narrates each one in the background.

    The step never waits for the narrator (an LLM can be slow). The last beat (`done` or `fail`) is not a step of its own:
    `close()` returns its text, which the agent puts in front of the JSON report.
    """

    def __init__(self, narrator: Narrator, sink: StepSink) -> None:
        self._narrator, self._sink = narrator, sink
        self._events: list[TraceEvent] = []
        self._queue: asyncio.Queue[Beat | None] = asyncio.Queue()
        self._consumer: asyncio.Task[None] | None = None
        self._task = Task(operation="", question="")
        self._closing: Beat | None = None

    async def emit(self, event: TraceEvent) -> None:
        if event.stage == "intake" and event.state == "note":
            self._task = Task(str(event.facts.get("operation", "")), str(event.facts.get("original_question", "")))
        if self._events and event.phase != self._events[-1].phase:
            self._flush()
        self._events.append(event)

    def _flush(self) -> None:
        if not self._events:
            return
        beat = Beat(self._events[0].phase, tuple(self._events))
        self._events = []
        if beat.phase in ("done", "fail"):
            self._closing = beat
            return
        if self._consumer is None:
            self._consumer = asyncio.create_task(self._run())
        self._queue.put_nowait(beat)

    async def _run(self) -> None:
        while (beat := await self._queue.get()) is not None:
            try:
                await self._sink.step(await self._narrator.narrate(beat, self._task), tool_calls_of(beat))
            except Exception:
                log.warning("data: narrating the %s phase failed", beat.phase, exc_info=True)

    async def close(self) -> str:
        """Wait for the narrated steps to be shown; returns the closing line (`""` if the run had no closing event)."""
        self._flush()
        if self._consumer is not None:
            self._queue.put_nowait(None)
            await self._consumer
        return await self._narrator.narrate(self._closing, self._task) if self._closing else ""

    async def abort(self) -> None:
        """Stop narrating (the turn was cancelled or failed)."""
        if self._consumer is not None and not self._consumer.done():
            self._consumer.cancel()
            await asyncio.gather(self._consumer, return_exceptions=True)
