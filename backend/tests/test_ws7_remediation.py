"""WS7 remediation: F-02 hash verification of superseded versions, F-03 run outcome → task status,
F-04 run_state reconciliation after a restart, F-11 explicit idempotency keys."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from conftest import ALICE, BOB, Harness, Session, wait_for
from test_api import A, B, client  # noqa: F401  (pytest fixture)
from vdagent_backend.db import artifact_store, repo
from vdagent_backend.db.database import apply_schema, create_db
from vdagent_contracts.envelope import ArtifactDraft

# ---- F-02 -------------------------------------------------------------------------------------------------------------


def _draft(**over: Any) -> ArtifactDraft:
    fields: dict[str, Any] = {"artifact_type": "run_state", "schema_version": "run_state@1", "status": "VALID",
                              "producer": {"agent": "orchestrator", "agent_version": "1"}, "snapshot_refs": ["SNAP-2026-09-28"],
                              "semantic_config_version": "sc-1", "payload": {"status": "running"}}
    fields.update(over)
    return ArtifactDraft.model_validate(fields)


async def test_current_and_superseded_versions_verify_against_their_stored_hash(tmp_path: Path) -> None:
    db = create_db(str(tmp_path / "b.db"))
    with sqlite3.connect(tmp_path / "b.db") as conn:
        conn.execute("INSERT INTO users (id, name) VALUES (?, 'Alice')", (ALICE,))
    conn.close()
    first = await artifact_store.put(db, user_id=ALICE, run_id="t_1", task_id="t_1", draft=_draft())
    second = await artifact_store.put(db, user_id=ALICE, run_id="t_1", task_id="t_1",
                                      draft=_draft(artifact_id=first.artifact_id, status="PARTIAL", limitations=["X"], payload={"status": "done"}))
    old = await artifact_store.get(db, ALICE, first.artifact_id, version=1)
    assert old is not None and old.status.value == "SUPERSEDED"
    assert old.content_hash == first.content_hash  # history is never rewritten
    assert artifact_store.verify(old) == (True, "VALID")  # verifiable, with its status at write time
    assert artifact_store.verify(second) == (True, "PARTIAL")
    tampered = old.model_copy(update={"payload": {"status": "forged"}})
    assert artifact_store.verify(tampered) == (False, None)
    await db.dispose()


# ---- F-03 -------------------------------------------------------------------------------------------------------------


async def _outcome_turn(harness: Harness, outcome: str | None) -> dict[str, Any]:
    async def handler(s: Session) -> None:
        if outcome is not None:
            s.ctx.report_outcome(outcome)  # type: ignore[attr-defined]
        await s.final(f"run outcome: {outcome}")

    harness.on("orchestrator", handler)
    task_id = await harness.post("orchestrator", "go")
    return await harness.wait_task(task_id)


@pytest.mark.parametrize(("outcome", "status"), [("failed", "failed"), ("partial", "completed"), ("completed", "completed"), (None, "completed")])
async def test_reported_run_outcome_sets_task_status(harness: Harness, outcome: str | None, status: str) -> None:
    row = await _outcome_turn(harness, outcome)
    assert row["status"] == status and row["outcome"] == outcome
    assert repo.task_dto(row)["outcome"] == outcome


async def test_unknown_outcome_is_a_contract_violation(harness: Harness) -> None:
    row = await _outcome_turn(harness, "great")
    assert row["status"] == "failed"


async def test_task_dto_exposes_outcome_over_rest(client: httpx.AsyncClient) -> None:
    app = client.app  # type: ignore[attr-defined]
    agents = app.state.services.engine.registry.get("orchestrator").agent

    async def handler(s: Session) -> None:
        s.ctx.report_outcome("partial")  # type: ignore[attr-defined]
        await s.final("partial run")

    agents.handler = handler
    task_id = (await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=A)).json()["task_id"]
    await wait_for(lambda: _done(client, task_id))
    task = (await client.get(f"/api/tasks/{task_id}", headers=A)).json()["task"]
    assert (task["status"], task["outcome"]) == ("completed", "partial")


async def _done(client: httpx.AsyncClient, task_id: str) -> bool:
    return (await client.get(f"/api/tasks/{task_id}", headers=A)).json()["task"]["status"] != "running"


# ---- F-04 -------------------------------------------------------------------------------------------------------------


async def test_restart_reconciles_running_run_states(harness: Harness) -> None:
    stall = asyncio.Event()

    async def handler(s: Session) -> None:
        await artifact_store.put(harness.db, user_id=ALICE, run_id=s.ctx.task_id, task_id=s.ctx.task_id,
                                 draft=_draft(payload={"status": "running", "plan_id": "pl_x",
                                                       "steps": [{"step_id": "B1", "status": "completed"}, {"step_id": "B2", "status": "running"},
                                                                 {"step_id": "B3", "status": "pending"}]}))
        await stall.wait()

    harness.on("orchestrator", handler)
    task_id = await harness.post("orchestrator", "go")
    await wait_for(lambda: artifact_store.list_artifacts(harness.db, ALICE, run_id=task_id))
    # simulate a crash: a fresh engine on the same DB runs its startup recovery
    from vdagent_backend.engine import Engine

    await harness.engine.stop()
    engine = Engine(harness.cfg, harness.db, harness.bus, harness.tokens, harness.registry)
    await engine.start()
    try:
        task = await repo.get_task(harness.db, task_id)
        assert task is not None and (task["status"], task["outcome"]) == ("failed", "interrupted")
        [state] = await artifact_store.list_artifacts(harness.db, ALICE, run_id=task_id, artifact_type="run_state")
        assert state.version == 2 and state.payload["status"] == "interrupted"
        assert [s["status"] for s in state.payload["steps"]] == ["completed", "interrupted", "interrupted"]
        assert state.payload["interrupted"]["reason"] == "backend restarted"
        v1 = await artifact_store.get(harness.db, ALICE, state.artifact_id, version=1)
        assert v1 is not None and v1.payload["status"] == "running" and artifact_store.verify(v1)[0]  # history kept
    finally:
        await engine.stop()


# ---- F-11 -------------------------------------------------------------------------------------------------------------


async def test_idempotency_key_returns_the_first_task(client: httpx.AsyncClient) -> None:
    h = {**A, "Idempotency-Key": "req-001"}
    first = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h)
    again = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h)
    assert first.status_code == 202 and again.status_code == 200
    assert again.json()["task_id"] == first.json()["task_id"] and again.json()["deduplicated"] is True
    tasks = (await client.get("/api/tasks", headers=A)).json()
    assert len([t for t in tasks if t["id"] == first.json()["task_id"]]) == 1 and len(tasks) == 1


async def test_concurrent_retries_with_one_key_start_one_task(client: httpx.AsyncClient) -> None:
    h = {**A, "Idempotency-Key": "req-002"}
    replies = await asyncio.gather(*(client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h) for _ in range(5)))
    assert len({r.json()["task_id"] for r in replies}) == 1
    assert len((await client.get("/api/tasks", headers=A)).json()) == 1


async def test_same_text_without_key_or_other_user_is_not_merged(client: httpx.AsyncClient) -> None:
    r1 = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=A)
    r2 = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=A)
    r3 = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers={**B, "Idempotency-Key": "req-003"})
    r4 = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers={**A, "Idempotency-Key": "req-003"})
    assert len({r1.json()["task_id"], r2.json()["task_id"], r3.json()["task_id"], r4.json()["task_id"]}) == 4


async def test_key_reused_with_other_content_is_a_conflict(client: httpx.AsyncClient) -> None:
    h = {**A, "Idempotency-Key": "req-004"}
    await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h)
    clash = await client.post("/api/agents/orchestrator/messages", json={"content": "something else"}, headers=h)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_conflict"


def test_schema_migration_adds_columns_to_an_existing_db(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:  # a pre-WS7 tasks table
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT)")
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, root_agent TEXT NOT NULL,"
                     " status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '', finished_at TEXT)")
        conn.execute("INSERT INTO tasks (id, user_id, root_agent, status) VALUES ('t_old', 'u', 'data', 'completed')")
    conn.close()
    apply_schema(str(path))
    apply_schema(str(path))  # idempotent
    with sqlite3.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        row = conn.execute("SELECT status, outcome, idempotency_key FROM tasks WHERE id = 't_old'").fetchone()
    conn.close()
    assert {"outcome", "idempotency_key"} <= cols and row == ("completed", None, None)
    _ = json  # keep import for readers of failing assertions
    _ = BOB


# ---- F-09 -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("kind", "y"), [("bar", ["dom"]), ("line", ["dom"]), ("pie", ["dom"]), ("bar", ["dom", "price"])])
def test_create_chart_emits_renderable_vega_lite_v6(kind: str, y: list[str]) -> None:
    from vdagent_backend.mcp.charts import build_chart_spec
    from vdagent_contracts.vega_lite import validate_vega_lite

    dataset = {"columns": [{"name": "project", "type": "TEXT"}, {"name": "dom", "type": "INTEGER"}, {"name": "price", "type": "REAL"}],
               "rows": [["P1", 138, 72.5], ["P2", 61, 64.5]]}
    assert validate_vega_lite(build_chart_spec(dataset, kind, "project", y, "DOM")) == []
