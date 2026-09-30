"""`core`: clock formatting and the shared error helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from vdagent_backend.core.clock import iso_ms, utcnow
from vdagent_backend.core.errors import describe, error_body


def test_iso_ms_renders_utc_with_milliseconds_and_z() -> None:
    plus7 = timezone(timedelta(hours=7))
    moment = datetime(2026, 9, 29, 17, 4, 5, 123456, tzinfo=plus7)
    assert iso_ms(moment) == "2026-09-29T10:04:05.123Z"


def test_utcnow_is_timezone_aware_utc() -> None:
    assert utcnow().utcoffset() == UTC.utcoffset(None)


def test_describe_names_the_type_and_unwraps_exception_groups() -> None:
    assert describe(ValueError("kaput")) == "ValueError: kaput"
    assert describe(TimeoutError()) == "TimeoutError"
    group = ExceptionGroup("outer", [ExceptionGroup("inner", [KeyError("k")]), ValueError("x")])
    assert describe(group) == "KeyError: 'k'"


def test_error_body_is_the_shared_envelope() -> None:
    assert error_body("not_found", "task not found") == {"error": {"code": "not_found", "message": "task not found"}}
