"""S1 of the Data pipeline (SPEC §2.4): the deterministic entity ladder. Pure functions first, then against the mock DW."""

from __future__ import annotations

from typing import Any

import pytest

from vdagent_data.resolve import (
    Candidate,
    Ladder,
    Unresolved,
    level_before,
    name_form,
    resolve_entities,
    unit_code_form,
)


@pytest.mark.parametrize("raw,expected", [
    ("A12-08", "A1208"), ("a12 08", "A1208"), ("A12.08", "A1208"), (" a12-08 ", "A1208"), ("OCP-U00001", "OCPU00001"),
])
def test_unit_codes_meet_in_one_form(raw: str, expected: str) -> None:
    assert unit_code_form(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Đồi Thông", "doi thong"), ("  Landmark   Plaza ", "landmark plaza"), ("Tòa Aqua 1", "toa aqua 1"), ("SÓNG", "song"),
])
def test_names_are_compared_without_case_diacritics_or_extra_spaces(raw: str, expected: str) -> None:
    assert name_form(raw) == expected


@pytest.mark.parametrize("question,mention,level", [
    ("Tại sao phân khu Landmark bán chậm?", "Landmark", "ZONE"),
    ("Tình hình dự án Đồi Thông thế nào", "Đồi Thông", "PROJECT"),
    ("Vì sao căn A12-08 bán chậm?", "A12-08", "UNIT"),
    ("Cho tôi xem Landmark", "Landmark", None),
    ("Phân khu Aqua và dự án Sông Xanh", "Sông Xanh", "PROJECT"),
    ("Phân khu Aqua và dự án Sông Xanh", "Aqua", "ZONE"),
    ("Landmark", "Không có trong câu", None),
])
def test_the_level_word_right_before_a_name_says_which_level_the_user_meant(question: str, mention: str, level: str | None) -> None:
    assert level_before(question, mention) == level


def zone(key: str, name: str, project: str = "P1") -> Candidate:
    return Candidate("ZONE", key, name, name, project)


def project(key: str, name: str) -> Candidate:
    return Candidate("PROJECT", key, name, name, key)


def unit(key: str, code: str, project: str = "P1") -> Candidate:
    return Candidate("UNIT", key, code, code, project)


POOL = [zone("Z1", "Tòa Landmark 1"), zone("Z2", "Landmark Plaza"), zone("Z3", "Tòa Aqua 1"), project("P1", "Khu đô thị Sông Xanh"),
        project("P2", "Landmark City"), unit("U1", "A12-08"), unit("U2", "B15-02", "P2")]


def test_one_exact_match_is_taken() -> None:
    result = Ladder(POOL).resolve("Landmark Plaza", "UNKNOWN", None)
    assert result.accepted and result.accepted.key == "Z2" and result.method == "exact"


def test_a_normalized_unit_code_is_taken() -> None:
    result = Ladder(POOL).resolve("a12.08", "UNIT", None)
    assert result.accepted and result.accepted.key == "U1" and result.method == "normalized"


def test_a_partial_name_that_matches_several_levels_is_ambiguous_not_guessed() -> None:
    result = Ladder(POOL).resolve("Landmark", "ZONE", None)
    assert result.accepted is None and {c.key for c in result.ambiguous} == {"Z1", "Z2", "P2"}


def test_the_hint_only_orders_the_choices() -> None:
    result = Ladder(POOL).resolve("Landmark", "ZONE", None)
    assert [c.kind for c in result.ambiguous][:2] == ["ZONE", "ZONE"] and result.ambiguous[-1].kind == "PROJECT"


def test_the_level_word_in_the_question_filters_the_candidates() -> None:
    result = Ladder(POOL).resolve("Landmark", "UNKNOWN", "ZONE")
    assert {c.key for c in result.ambiguous} == {"Z1", "Z2"}
    result = Ladder(POOL).resolve("Landmark", "UNKNOWN", "PROJECT")
    assert result.accepted and result.accepted.key == "P2"


def test_a_level_word_that_empties_the_candidates_asks_instead_of_dropping_the_filter() -> None:
    result = Ladder(POOL).resolve("Aqua", "UNKNOWN", "PROJECT")
    assert result.accepted is None and [c.key for c in result.ambiguous] == ["Z3"] and result.wrong_level


def test_a_typed_diacritic_keeps_only_the_candidates_that_match_it() -> None:
    pool = [zone("Z1", "Tòa Sóng"), zone("Z2", "Tòa Song")]
    assert Ladder(pool).resolve("Sóng", "ZONE", None).ambiguous == []
    assert Ladder(pool).resolve("Sóng", "ZONE", None).accepted.key == "Z1"  # type: ignore[union-attr]


def test_a_saved_choice_is_reused_without_asking() -> None:
    result = Ladder(POOL, saved={"landmark": "Z2"}).resolve("Landmark", "ZONE", None)
    assert result.accepted and result.accepted.key == "Z2" and result.method == "saved_choice"


def test_a_saved_choice_outside_the_candidates_is_ignored() -> None:
    result = Ladder(POOL, saved={"landmark": "Z9"}).resolve("Landmark", "ZONE", None)
    assert result.accepted is None and result.ambiguous


def test_nothing_found_gives_the_nearest_names_to_choose_from() -> None:
    result = Ladder(POOL).resolve("Landmak Plaza", "ZONE", None)
    assert result.accepted is None and not result.ambiguous
    assert result.suggestions and result.suggestions[0].key == "Z2"


def test_nothing_close_at_all_gives_no_suggestion() -> None:
    result = Ladder(POOL).resolve("zzzzzz", "ZONE", None)
    assert result.accepted is None and not result.ambiguous and result.suggestions == []


def test_an_empty_pool_is_out_of_scope() -> None:
    assert Ladder([]).resolve("Landmark", "ZONE", None).empty_scope


# ---- against (a fake of) the warehouse ------------------------------------------------------------------------------------

ZONES = [{"zone_key": "Z1", "zone_name": "Tòa Landmark 1", "project_key": "P1"}, {"zone_key": "Z2", "zone_name": "Landmark Plaza", "project_key": "P1"},
         {"zone_key": "Z3", "zone_name": "Tòa Aqua 1", "project_key": "P1"}]
PROJECTS = [{"project_key": "P1", "project_name": "Khu đô thị Sông Xanh"}]
UNITS = [{"unit_key": "U1", "unit_code": "A12-08", "project_key": "P1"}, {"unit_key": "U2", "unit_code": "A12-11", "project_key": "P1"}]


class FakeDw:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def __call__(self, table: str, sql: str, why: str) -> list[dict[str, Any]]:
        self.sql.append(sql)
        assert why  # every read says why (trace)
        if table == "dim_zone_master":
            return ZONES
        if table == "dim_project_profile":
            return PROJECTS
        if "= 'A1208'" in sql:
            return UNITS[:1]
        if "LIKE 'A" in sql:
            return UNITS
        return []


async def test_a_unit_code_typed_loosely_is_found_by_its_canonical_form() -> None:
    [r] = await resolve_entities(FakeDw(), [("a12 08", "UNKNOWN")], "Vì sao căn a12 08 bán chậm?")
    assert r.candidate.kind == "UNIT" and r.candidate.code == "A12-08" and r.method == "normalized"


async def test_the_code_is_only_ever_embedded_as_letters_and_digits() -> None:
    dw = FakeDw()
    with pytest.raises(Unresolved):
        await resolve_entities(dw, [("A12-08'; DROP TABLE x;--", "UNIT")], "q")
    unit_sql = [s for s in dw.sql if "dim_unit_master" in s]
    assert unit_sql and all(";" not in s and "--" not in s and "DROP TABLE" not in s for s in unit_sql)


async def test_a_zone_name_that_fits_two_zones_asks_with_both() -> None:
    with pytest.raises(Unresolved) as info:
        await resolve_entities(FakeDw(), [("Landmark", "ZONE")], "Tại sao phân khu Landmark bán chậm?")
    assert info.value.code == "AMBIGUOUS_REQUEST" and {c.key for c in info.value.options} == {"Z1", "Z2"}


async def test_a_saved_choice_answers_the_same_question_again() -> None:
    [r] = await resolve_entities(FakeDw(), [("Landmark", "ZONE")], "Tại sao phân khu Landmark bán chậm?", saved={"landmark": "Z1"})
    assert r.candidate.key == "Z1" and r.method == "saved_choice"


async def test_an_unknown_unit_gets_the_nearest_codes_as_choices() -> None:
    with pytest.raises(Unresolved) as info:
        await resolve_entities(FakeDw(), [("A12-09", "UNIT")], "Vì sao căn A12-09 bán chậm?")
    assert info.value.code == "ENTITY_NOT_FOUND" and [c.code for c in info.value.options][:1] == ["A12-08"]


async def test_nothing_near_is_out_of_scope_not_an_invented_suggestion() -> None:
    with pytest.raises(Unresolved) as info:
        await resolve_entities(FakeDw(), [("qqqqqq", "ZONE")], "phân khu qqqqqq")
    assert info.value.code == "OUT_OF_SCOPE"


async def test_the_first_entity_that_cannot_be_taken_stops_the_others() -> None:
    with pytest.raises(Unresolved) as info:
        await resolve_entities(FakeDw(), [("Tòa Aqua 1", "ZONE"), ("Landmark", "ZONE")], "so sánh Tòa Aqua 1 với phân khu Landmark")
    assert info.value.mention == "Landmark"
