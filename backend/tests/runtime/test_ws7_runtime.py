"""WS7 on backend v2: F-03 run outcome → task status, F-04 run_state reconciliation after a restart, F-11 engine-level
idempotency keys."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from conftest import ALICE, BOB, Harness, Session, wait_for
from vdagent_backend.artifacts import ArtifactService, verify_envelope
from vdagent_backend.conversations import task_dto
from vdagent_backend.runtime import Engine, IdempotencyConflictError
from vdagent_contracts.envelope import ArtifactDraft


def _run_state(payload: dict[str, Any]) -> ArtifactDraft:
    return ArtifactDraft.model_validate({
        "artifact_type": "run_state", "schema_version": "run_state@1", "status": "VALID",
        "producer": {"agent": "orchestrator", "agent_version": "1"}, "snapshot_refs": ["SNAP-2026-09-28"],
        "semantic_config_version": "sc-1", "payload": payload,
    })


# ---- F-03 -------------------------------------------------------------------------------------------------------------


async def _outcome_turn(harness: Harness, outcome: str | None) -> dict[str, Any]:
    async def handler(s: Session) -> None:
        if outcome is not None:
            s.ctx.report_outcome(outcome)  # type: ignore[attr-defined]
        await s.final(f"run outcome: {outcome}")

    harness.on("orchestrator", handler)
    return await harness.wait_task(await harness.post("orchestrator", "go"))


@pytest.mark.parametrize(("outcome", "status"), [("failed", "failed"), ("partial", "completed"), ("completed", "completed"), (None, "completed")])
async def test_reported_run_outcome_sets_task_status(harness: Harness, outcome: str | None, status: str) -> None:
    row = await _outcome_turn(harness, outcome)
    assert (row["status"], row["outcome"]) == (status, outcome)
    assert task_dto(row)["outcome"] == outcome


async def test_unknown_outcome_is_a_contract_violation(harness: Harness) -> None:
    assert (await _outcome_turn(harness, "great"))["status"] == "failed"


async def test_a_child_outcome_does_not_touch_the_task(harness: Harness) -> None:
    async def child(s: Session) -> None:
        s.ctx.report_outcome("failed")  # type: ignore[attr-defined]
        await s.final("child says failed")

    async def root(s: Session) -> None:
        await s.ask("data", "go")
        await s.final("root done")

    harness.on("data", child)
    harness.on("orchestrator", root)
    row = await harness.wait_task(await harness.post("orchestrator", "go"))
    assert (row["status"], row["outcome"]) == ("completed", None)


# ---- F-04 -------------------------------------------------------------------------------------------------------------


async def test_restart_fails_the_task_as_interrupted_and_reconciles_its_run_state(harness: Harness) -> None:
    artifacts, stall = ArtifactService(harness.db), asyncio.Event()

    async def handler(s: Session) -> None:
        await artifacts.put_envelope(ALICE, s.ctx.task_id, s.ctx.task_id, _run_state({
            "status": "running", "plan_id": "pl_x",
            "steps": [{"step_id": "B1", "status": "completed"}, {"step_id": "B2", "status": "running"},
                      {"step_id": "B3", "status": "pending"}]}))
        await stall.wait()

    harness.on("orchestrator", handler)
    task_id = await harness.post("orchestrator", "go")
    await wait_for(lambda: artifacts.list_envelopes(ALICE, run_id=task_id))
    await harness.engine.stop()  # crash; a fresh engine on the same DB runs startup recovery with the artifact hook
    engine = Engine(harness.cfg, harness.db, harness.bus, harness.tokens, harness.registry, on_interrupted=artifacts.interrupt_run)
    await engine.recover()
    try:
        task = await harness.tasks.get_task(task_id)
        assert task is not None and (task["status"], task["outcome"]) == ("failed", "interrupted")
        [state] = await artifacts.list_envelopes(ALICE, run_id=task_id, artifact_type="run_state")
        assert state.version == 2 and state.payload["status"] == "interrupted" and state.status.value == "INVALID"
        assert [s["status"] for s in state.payload["steps"]] == ["completed", "interrupted", "interrupted"]
        assert state.payload["interrupted"]["reason"] == "backend restarted"
        v1 = await artifacts.get_envelope(ALICE, state.artifact_id, 1)
        assert v1 is not None and v1.payload["status"] == "running" and verify_envelope(v1)[0]  # history kept
    finally:
        await engine.stop()


async def test_recovery_hook_failure_never_blocks_startup(harness: Harness) -> None:
    stall = asyncio.Event()

    async def handler(s: Session) -> None:
        await stall.wait()

    async def broken(user_id: str, task_id: str) -> Any:
        raise RuntimeError("store down")

    harness.on("orchestrator", handler)
    task_id = await harness.post("orchestrator", "go")
    await wait_for(lambda: harness.invocations(task_id))
    await harness.engine.stop()
    engine = Engine(harness.cfg, harness.db, harness.bus, harness.tokens, harness.registry, on_interrupted=broken)
    await engine.recover()
    await engine.stop()
    assert (await harness.tasks.get_task(task_id) or {})["outcome"] == "interrupted"


# ---- F-11 -------------------------------------------------------------------------------------------------------------


async def test_idempotency_key_returns_the_first_task_and_flags_it(harness: Harness) -> None:
    first, _ = await harness.engine.post_message(ALICE, "orchestrator", "go", idempotency_key="k1")
    again, _ = await harness.engine.post_message(ALICE, "orchestrator", "go", idempotency_key="k1")
    assert again["id"] == first["id"] and again["deduplicated"] is True and "deduplicated" not in first
    other_user, _ = await harness.engine.post_message(BOB, "orchestrator", "go", idempotency_key="k1")
    no_key, _ = await harness.engine.post_message(ALICE, "orchestrator", "go")
    assert len({first["id"], other_user["id"], no_key["id"]}) == 3
    with pytest.raises(IdempotencyConflictError):
        await harness.engine.post_message(ALICE, "orchestrator", "something else", idempotency_key="k1")


async def test_concurrent_retries_with_one_key_start_one_task(harness: Harness) -> None:
    rows = await asyncio.gather(*(harness.engine.post_message(ALICE, "orchestrator", "go", idempotency_key="k2") for _ in range(5)))
    assert len({task["id"] for task, _ in rows}) == 1
    assert len(await harness.tasks.list_tasks(ALICE)) == 1
