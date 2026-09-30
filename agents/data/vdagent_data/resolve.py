"""S1: the deterministic entity ladder (SPEC §2.4). No LLM chooses an entity, and nothing outside the caller's scope is here.

The pool the ladder works on is what the Backend's scoped views show, so scope filtering (rung 3) has already happened
when a `Candidate` exists. Rungs: a saved choice, then exact / normalized / word-contained lookup at every level, then the
level word the user wrote ("phân khu", "dự án", "căn"), then the count. The caller's `kind_hint` only orders the choices.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

Kind = Literal["PROJECT", "ZONE", "UNIT"]
Method = Literal["exact", "normalized", "contains", "saved_choice"]

SUGGESTION_CUTOFF = 0.6
MAX_SUGGESTIONS = 5
_LEVEL_WORDS: tuple[tuple[str, Kind], ...] = (("phan khu", "ZONE"), ("du an", "PROJECT"), ("can ho", "UNIT"), ("can", "UNIT"))


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    key: str
    code: str  # unit code, or the name for zones and projects
    label: str
    project_key: str


def _strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def name_form(text: str) -> str:
    """Case, diacritics, punctuation and spacing removed: "Tòa  Aqua-1" and "toa aqua 1" meet."""
    return re.sub(r"[^a-z0-9]+", " ", _strip_marks(text).lower()).strip()


def unit_code_form(text: str) -> str:
    """The canonical form of a unit code: "a12 08", "A12.08" and "A12-08" are one code."""
    return re.sub(r"[^A-Z0-9]", "", _strip_marks(text).upper())


def _plain(text: str) -> str:
    return " ".join(text.casefold().split())


def level_before(question: str, mention: str) -> Kind | None:
    """The level word written right before `mention` in the question, if any."""
    q, m = name_form(question), name_form(mention)
    at = q.find(m) if m else -1
    if at < 0:
        return None
    before = q[:at].strip()
    for word, kind in _LEVEL_WORDS:
        if before == word or before.endswith(" " + word):
            return kind
    return None


def split_level(mention: str) -> tuple[Kind | None, str]:
    """"phân khu Landmark" → (ZONE, "Landmark"): a level word the user wrote inside the mention itself."""
    words, form = mention.split(), name_form(mention).split()
    for word, kind in _LEVEL_WORDS:
        head = word.split()
        if len(form) > len(head) and form[: len(head)] == head and len(words) > len(head):
            return kind, " ".join(words[len(head):])
    return None, mention


@dataclass
class Resolution:
    mention: str
    accepted: Candidate | None = None
    method: Method | None = None
    ambiguous: list[Candidate] = field(default_factory=list)
    suggestions: list[Candidate] = field(default_factory=list)
    wrong_level: bool = False
    empty_scope: bool = False


class Ladder:
    def __init__(self, pool: Sequence[Candidate], saved: Mapping[str, str] | None = None) -> None:
        self._pool = list(pool)
        self._saved = dict(saved or {})

    def resolve(self, mention: str, hint: str, level: Kind | None) -> Resolution:
        result = Resolution(mention)
        if not self._pool:
            result.empty_scope = True
            return result
        matches, method = self._lookup(mention)
        saved_key = self._saved.get(name_form(mention))
        if saved_key is not None:
            chosen = next((c for c in self._pool if c.key == saved_key and (level is None or c.kind == level)), None)
            if chosen is not None:
                result.accepted, result.method = chosen, "saved_choice"
                return result
        if not matches:
            result.suggestions = self._nearest(mention, hint)
            return result
        if level is not None:
            kept = [c for c in matches if c.kind == level]
            if not kept:
                result.wrong_level, result.ambiguous = True, _ordered(matches, hint)
                return result
            matches = kept
        if len(matches) == 1:
            result.accepted, result.method = matches[0], method
            return result
        result.ambiguous = _ordered(matches, hint)
        return result

    def _lookup(self, mention: str) -> tuple[list[Candidate], Method]:
        plain, form, code = _plain(mention), name_form(mention), unit_code_form(mention)
        exact = [c for c in self._pool if _plain(c.label) == plain]
        if exact:
            return exact, "exact"
        normalized = [c for c in self._pool if name_form(c.label) == form or (c.kind == "UNIT" and unit_code_form(c.label) == code)]
        if normalized:
            return _keep_typed_marks(mention, normalized), "normalized"
        words = set(form.split())
        contains = [c for c in self._pool if c.kind != "UNIT" and words and words <= set(name_form(c.label).split())]
        return _keep_typed_marks(mention, contains), "contains"

    def _nearest(self, mention: str, hint: str) -> list[Candidate]:
        form = name_form(mention)
        scored = []
        for c in self._pool:
            target = unit_code_form(c.label) if c.kind == "UNIT" else name_form(c.label)
            ratio = SequenceMatcher(None, unit_code_form(mention) if c.kind == "UNIT" else form, target).ratio()
            if ratio >= SUGGESTION_CUTOFF:
                scored.append((-ratio, c.kind != hint, c.label, c))
        scored.sort(key=lambda t: t[:3])
        return [t[3] for t in scored[:MAX_SUGGESTIONS]]


def _keep_typed_marks(mention: str, matches: list[Candidate]) -> list[Candidate]:
    """"Sóng" typed with marks and some candidates matching with them: only those (SPEC §2.4 rung 2)."""
    if _strip_marks(mention) == mention:
        return matches
    same = [c for c in matches if _plain(mention) in _plain(c.label) or set(_plain(mention).split()) <= set(_plain(c.label).split())]
    return same or matches


def _ordered(matches: list[Candidate], hint: str) -> list[Candidate]:
    return sorted(matches, key=lambda c: (c.kind != hint, c.label))


# ---- against the warehouse ---------------------------------------------------------------------------------------------

_UNIT_FORM_SQL = "REPLACE(REPLACE(REPLACE(UPPER(unit_code), '-', ''), '.', ''), ' ', '')"
UNIT_SUGGESTION_ROWS = 3_000

Select = Callable[[str, str, str], Awaitable[list[dict[str, Any]]]]  # (table, sql, why) -> rows: `_Run.select`


class Unresolved(Exception):
    """A mention the ladder could not turn into exactly one entity: the step asks, or it is out of scope."""

    def __init__(self, code: Literal["AMBIGUOUS_REQUEST", "ENTITY_NOT_FOUND", "OUT_OF_SCOPE"], mention: str, message: str,
                 options: list[Candidate] | None = None) -> None:
        super().__init__(message)
        self.code, self.mention, self.message, self.options = code, mention, message, options or []


@dataclass(frozen=True)
class Resolved:
    mention: str
    candidate: Candidate
    method: Method


async def _pool(select: Select, mention: str, hint: str, level: Kind | None) -> list[Candidate]:
    pool: list[Candidate] = []
    if level in (None, "PROJECT"):
        rows = await select("dim_project_profile", "SELECT project_key, project_name FROM dim_project_profile",
                            "Lấy tên các dự án trong phạm vi quyền để đối chiếu tên người dùng gọi")
        pool += [Candidate("PROJECT", str(r["project_key"]), r["project_name"], r["project_name"], str(r["project_key"])) for r in rows]
    if level in (None, "ZONE"):
        rows = await select("dim_zone_master", "SELECT zone_key, zone_name, project_key FROM dim_zone_master",
                            "Lấy tên các phân khu trong phạm vi quyền để đối chiếu tên người dùng gọi")
        pool += [Candidate("ZONE", str(r["zone_key"]), r["zone_name"], r["zone_name"], str(r["project_key"])) for r in rows]
    code = unit_code_form(mention)
    looks_like_code = level == "UNIT" or hint == "UNIT" or any(ch.isdigit() for ch in mention)
    if level in (None, "UNIT") and looks_like_code and code:
        rows = await select("dim_unit_master",
                            f"SELECT unit_key, unit_code, project_key FROM dim_unit_master WHERE {_UNIT_FORM_SQL} = '{code}'",
                            f"Tìm căn có mã {mention} (chuẩn hóa dấu gạch, dấu chấm và khoảng trắng) trong phạm vi quyền")
        if not rows:
            prefix = re.match(r"[A-Z]+", code)
            if prefix:
                rows = await select("dim_unit_master",
                                    "SELECT unit_key, unit_code, project_key FROM dim_unit_master"
                                    f" WHERE UPPER(unit_code) LIKE '{prefix.group()[:3]}%' LIMIT {UNIT_SUGGESTION_ROWS}",
                                    f"Không thấy mã {mention}: lấy các mã cùng tiền tố trong phạm vi quyền để gợi ý mã gần nhất")
        pool += [Candidate("UNIT", str(r["unit_key"]), r["unit_code"], r["unit_code"], str(r["project_key"])) for r in rows]
    return pool


async def resolve_entities(select: Select, entities: Sequence[tuple[str, str]], question: str,
                           saved: Mapping[str, str] | None = None) -> list[Resolved]:
    """Every `(mention, kind_hint)` to exactly one entity, or `Unresolved` for the first that is not (SPEC §2.4)."""
    out: list[Resolved] = []
    for mention, hint in entities:
        level = level_before(question, mention)
        result = Ladder(await _pool(select, mention, hint, level), saved).resolve(mention, hint, level)
        if result.accepted is None and not result.ambiguous and not result.empty_scope:
            inner, rest = split_level(mention)  # "phân khu Landmark": only when the name as written found nothing
            if inner is not None:
                aliased = dict(saved or {})
                if name_form(mention) in aliased:
                    aliased[name_form(rest)] = aliased[name_form(mention)]
                again = Ladder(await _pool(select, rest, hint, inner), aliased).resolve(rest, hint, inner)
                if again.accepted is not None or again.ambiguous or again.empty_scope:
                    result = again
        if result.empty_scope:
            raise Unresolved("OUT_OF_SCOPE", mention, f"Không có đối tượng nào trong phạm vi quyền của bạn khớp với “{mention}”.")
        if result.accepted is not None and result.method is not None:
            out.append(Resolved(mention, result.accepted, result.method))
        elif result.ambiguous:
            why = "sai cấp so với từ bạn viết" if result.wrong_level else "khớp nhiều đối tượng"
            raise Unresolved("AMBIGUOUS_REQUEST", mention, f"“{mention}” {why}. Bạn muốn chọn đối tượng nào?", result.ambiguous)
        elif result.suggestions:
            raise Unresolved("ENTITY_NOT_FOUND", mention, f"Không thấy “{mention}” trong phạm vi của bạn. Có phải ý bạn là:", result.suggestions)
        else:
            raise Unresolved("OUT_OF_SCOPE", mention, f"Không tìm thấy “{mention}” trong phạm vi quyền của bạn.")
    return out
