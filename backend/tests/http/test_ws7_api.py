"""WS7 over REST on backend v2: Idempotency-Key, task outcome, chart_spec delivery, create_chart Vega-Lite v6."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from conftest import ALICE, Session, wait_for
from test_api import A, B, _task_status, client  # noqa: F401  (pytest fixture)
from vdagent_backend.artifacts import ArtifactService
from vdagent_contracts.envelope import ArtifactDraft


async def test_idempotency_key_returns_the_first_task(client: httpx.AsyncClient) -> None:
    h = {**A, "Idempotency-Key": "req-001"}
    first = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h)
    again = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h)
    assert first.status_code == 202 and again.status_code == 200
    assert first.json()["deduplicated"] is False and again.json() == {**first.json(), "deduplicated": True}
    assert len((await client.get("/api/tasks", headers=A)).json()) == 1


async def test_concurrent_retries_start_one_task_and_other_texts_are_never_merged(client: httpx.AsyncClient) -> None:
    h = {**A, "Idempotency-Key": "req-002"}
    replies = await asyncio.gather(*(client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h) for _ in range(5)))
    assert len({r.json()["task_id"] for r in replies}) == 1
    r1 = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=A)
    r2 = await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers={**B, "Idempotency-Key": "req-002"})
    assert len({replies[0].json()["task_id"], r1.json()["task_id"], r2.json()["task_id"]}) == 3


async def test_key_reused_with_other_content_is_a_conflict(client: httpx.AsyncClient) -> None:
    h = {**A, "Idempotency-Key": "req-004"}
    await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=h)
    clash = await client.post("/api/agents/orchestrator/messages", json={"content": "something else"}, headers=h)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_conflict"


async def test_task_dto_exposes_outcome(client: httpx.AsyncClient) -> None:
    app = client.app  # type: ignore[attr-defined]
    agent = app.state.services.engine.registry.get("orchestrator").agent

    async def handler(s: Session) -> None:
        s.ctx.report_outcome("partial")  # type: ignore[attr-defined]
        await s.final("partial run")

    agent.handler = handler
    task_id = (await client.post("/api/agents/orchestrator/messages", json={"content": "go"}, headers=A)).json()["task_id"]
    await wait_for(lambda: _task_status(client, task_id))
    task = (await client.get(f"/api/tasks/{task_id}", headers=A)).json()["task"]
    assert (task["status"], task["outcome"]) == ("completed", "partial")
    assert [t["outcome"] for t in (await client.get("/api/tasks", headers=A)).json()] == ["partial"]


async def test_chart_spec_delivery_is_owner_scoped(client: httpx.AsyncClient) -> None:
    task_id = (await client.post("/api/agents/data/messages", json={"content": "x"}, headers=A)).json()["task_id"]
    await wait_for(lambda: _task_status(client, task_id))
    app = client.app  # type: ignore[attr-defined]
    stored = await app.state.services.artifacts.put_envelope(ALICE, task_id, task_id, ArtifactDraft.model_validate({
        "artifact_type": "chart_spec", "schema_version": "chart_spec@1", "status": "VALID",
        "producer": {"agent": "chart", "agent_version": "test"}, "snapshot_refs": ["SNAP-2026-09-28"],
        "semantic_config_version": "sc-1",
        "payload": {"title": "DOM mục tiêu và nhóm tương đồng", "chart_type": "bar",
                    "vega_lite": {"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "data": {"values": []}},
                    "plotly": {"renderer": "plotly", "data": [], "layout": {"title": "DOM"}, "config": {"responsive": True}},
                    "dataset": [], "bindings": []},
    }))
    url = f"/api/chart-specs/{stored.artifact_id}/{stored.version}"
    body = (await client.get(url, headers=A)).json()
    assert (body["id"], body["version"], body["title"], body["chart_type"]) == (stored.artifact_id, 1, "DOM mục tiêu và nhóm tương đồng", "bar")
    assert body["spec"]["$schema"].endswith("/v6.json")
    assert body["plotly"]["renderer"] == "plotly"
    assert body["plotly"]["layout"]["title"] == "DOM"
    assert (await client.get(url, headers=B)).status_code == 404
    assert (await client.get(f"/api/chart-specs/{stored.artifact_id}/2", headers=A)).status_code == 404


@pytest.mark.parametrize(("kind", "y"), [("bar", ["dom"]), ("line", ["dom"]), ("pie", ["dom"]), ("bar", ["dom", "price"])])
def test_create_chart_emits_renderable_vega_lite_v6(kind: str, y: list[str]) -> None:  # WS7 F-09
    from vdagent_backend.artifacts.charts import build_chart_spec
    from vdagent_contracts.vega_lite import validate_vega_lite

    dataset = {"columns": [{"name": "project", "type": "TEXT"}, {"name": "dom", "type": "INTEGER"}, {"name": "price", "type": "REAL"}],
               "rows": [["P1", 138, 72.5], ["P2", 61, 64.5]]}
    assert validate_vega_lite(build_chart_spec(dataset, kind, "project", y, "DOM")) == []
    _ = ArtifactService
