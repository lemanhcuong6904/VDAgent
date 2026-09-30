from decimal import Decimal

import pytest

from vdagent_contracts.canonical import (
    RUN_IDENTITY_FIELDS,
    canonical_json,
    content_hash,
    percentile_inc,
    q2,
)


def _payload(run_id: str) -> dict[str, object]:
    return {
        "artifact_id": f"art_{run_id}",
        "run_id": run_id,
        "task_id": run_id,
        "version": 1,
        "created_at": "2026-09-29T00:00:00Z",
        "input_artifact_refs": [{"artifact_id": f"x_{run_id}"}],
        "content_hash": "stale",
        "idempotency_key": f"PLAN-{run_id}:B1",
        "plan_id": f"PLAN-{run_id}",
        "payload": {"median": Decimal("64500000"), "unit": "A12-08", "peers": ["A12-11", "A10-02"]},
    }


def test_hash_stable_across_runs() -> None:
    hashes = {content_hash(_payload(run)) for run in ("t_1", "t_2", "t_3")}
    assert len(hashes) == 1
    assert len(hashes.pop()) == 64


def test_hash_ignores_run_identity_fields() -> None:
    base = _payload("t_1")
    stripped = {k: v for k, v in base.items() if k not in RUN_IDENTITY_FIELDS}
    assert content_hash(base) == content_hash(stripped)
    changed = dict(base, payload={**base["payload"], "unit": "A12-09"})  # type: ignore[dict-item]
    assert content_hash(changed) != content_hash(base)


def test_decimal_serialized_as_string() -> None:
    text = canonical_json({"b": Decimal("12.40"), "a": "căn"})
    assert text == '{"a":"căn","b":"12.40"}'


def test_float_rejected_in_canonical_payload() -> None:
    with pytest.raises(TypeError):
        canonical_json({"x": 0.1})


def test_round_half_up_2dp() -> None:
    assert q2(Decimal("12.405")) == Decimal("12.41")
    assert q2(Decimal("126.2295")) == Decimal("126.23")
    assert q2(Decimal("-0.005")) == Decimal("-0.01")


def test_percentile_inc_linear_interpolation() -> None:
    prices = [Decimal(v) for v in ("60000000", "61500000", "62500000", "64500000", "67000000", "69000000", "70000000")]
    assert percentile_inc(prices, Decimal("0.5")) == Decimal("64500000")
    assert percentile_inc(prices, Decimal("0.25")) == Decimal("62000000")
    assert percentile_inc(prices, Decimal("0.75")) == Decimal("68000000")
    assert percentile_inc([Decimal(5)], Decimal("0.3")) == Decimal(5)
    with pytest.raises(ValueError):
        percentile_inc([], Decimal("0.5"))
