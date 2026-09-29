"""S0 intake (build spec 02 §5): spec validation, idempotency, snapshot lock, semantic version, RBAC scope."""

from __future__ import annotations

from vdagent_data.pipeline.s0_intake import Failure, Intake, intake
from vdagent_data.pipeline.s7_materialize import build_package, persist
from vdagent_data.tests.conftest import step
from vdagent_data.tests.fakes import DwMcp


async def test_s0_invalid_spec_spec_mismatch_or_error(dw_path: str) -> None:
    result = await intake(step(spec={"objective": "x", "scope": {"mentions": [], "scope_all": True}, "metrics": ["profit"]}),
                          DwMcp(dw_path), user_id="u_000000000001")
    assert isinstance(result, Failure) and result.code == "SPEC_MISMATCH" and "profit" in result.reason
    unknown_op = await intake(step(operation="delete_units"), DwMcp(dw_path), user_id="u_000000000001")
    assert isinstance(unknown_op, Failure) and unknown_op.code == "OUT_OF_SCOPE"


async def test_s0_same_idempotency_key_returns_stored_package(dw_path: str) -> None:
    mcp = DwMcp(dw_path)
    draft = build_package(operation="aggregate_metrics", snapshot_id="SNAP-2026-09-28", semantic_config_version="sc-1",
                          resolved={}, entries=[], dq=[], lineage=[], summary="x",
                          idempotency_key="PLAN-1:B1")
    stored = await persist(mcp, draft)
    result = await intake(step(), mcp, user_id="u_000000000001")
    assert isinstance(result, Intake) and result.reused is not None
    assert result.reused["artifact_id"] == stored["artifact_id"]
    other = await intake(step(step_id="B2"), mcp, user_id="u_000000000001")
    assert isinstance(other, Intake) and other.reused is None


async def test_s0_null_snapshot_locks_latest_approved(dw_path: str) -> None:
    result = await intake(step(), DwMcp(dw_path), user_id="u_000000000001")
    assert isinstance(result, Intake)
    assert (result.snapshot_id, result.snapshot_key, result.semantic_config_version) == ("SNAP-2026-09-28", 20260928, "sc-1")
    assert result.config["overdue_threshold_days"] == 90  # the DRAFT load of 09-29 is ignored


async def test_s0_unknown_snapshot_dq_blocking(dw_path: str) -> None:
    for snapshot in ("SNAP-1999-01-01", "SNAP-2026-09-29"):  # unknown, and DRAFT (not approved)
        result = await intake(step(snapshot_id=snapshot), DwMcp(dw_path), user_id="u_000000000001")
        assert isinstance(result, Failure) and result.code == "DQ_BLOCKING", snapshot
    pinned = await intake(step(snapshot_id="SNAP-2026-08-31"), DwMcp(dw_path), user_id="u_000000000001")
    assert isinstance(pinned, Intake) and pinned.snapshot_key == 20260831


async def test_s0_semantic_version_mismatch_dq_blocking(dw_path: str) -> None:
    result = await intake(step(snapshot_id="SNAP-2026-09-28", semantic_config_version="sc-0"), DwMcp(dw_path),
                          user_id="u_000000000001")
    assert isinstance(result, Failure) and result.code == "DQ_BLOCKING" and "sc-0" in result.reason


async def test_s0_scope_from_get_user_context(dw_path: str) -> None:
    widened = step(user_context={"user_id": "u_000000000001", "authorized_scope": {"project_ids": ["PRJ-X", "PRJ-Y"]}})
    result = await intake(widened, DwMcp(dw_path), user_id="u_000000000001")
    assert isinstance(result, Intake) and result.scope.project_ids == ["PRJ-X"]  # the message never widens scope


async def test_s0_out_of_scope_project(dw_path: str) -> None:
    stranger = await intake(step(), DwMcp(dw_path, user_id="u_nobody"), user_id="u_nobody")
    assert isinstance(stranger, Failure) and stranger.code == "OUT_OF_SCOPE"
    impostor = await intake(step(), DwMcp(dw_path), user_id="u_000000000002")
    assert isinstance(impostor, Failure) and impostor.code == "OUT_OF_SCOPE"
    assert "PRJ" not in impostor.reason  # no scope detail leaks
