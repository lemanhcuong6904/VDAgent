"""REST API through the real app, with fake agents loaded as a plugin."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from conftest import (
    ALICE,
    BOB,
    FakeAgent,
    Session,
    app_client,
    install_plugin,
    make_config,
    migrated_database,
    seed_users,
    wait_for,
)
from vdagent_backend.artifacts import Artifacts

A = {"X-User-Id": ALICE}
B = {"X-User-Id": BOB}


@pytest.fixture
async def client(
    tmp_path: Path, fake_agents: dict[str, FakeAgent], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    spec = install_plugin(monkeypatch, "fake_agents_plugin", fake_agents)
    cfg = make_config(tmp_path, plugins=[spec])
    await (await migrated_database(cfg.backend_db)).dispose()
    seed_users(cfg.backend_db)
    async with app_client(cfg) as c:
        yield c


async def _task_status(c: httpx.AsyncClient, task_id: str, headers: dict[str, str] = A) -> str | None:
    status = (await c.get(f"/api/tasks/{task_id}", headers=headers)).json()["task"]["status"]
    return status if status != "running" else None


async def test_identity_is_required(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/users")).status_code == 200
    for headers in ({}, {"X-User-Id": "u_nobody"}):
        r = await client.get("/api/agents", headers=headers)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unknown_user"


async def test_created_user_can_use_the_api(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/users", json={"name": "Carol"})
    assert r.status_code == 201
    carol = r.json()
    assert carol["id"].startswith("u_") and carol["name"] == "Carol"
    assert (await client.get("/api/agents", headers={"X-User-Id": carol["id"]})).status_code == 200


async def test_post_message_runs_task_and_chat_shows_it(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/agents/data/messages", json={"content": "hello"}, headers=A)
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    assert await wait_for(lambda: _task_status(client, task_id)) == "completed"

    chat = (await client.get("/api/agents/data/messages", headers=A)).json()
    assert [(m["seq"], m["role"], m["sender"], m["content"]) for m in chat["messages"]] == [
        (1, "user", "user", "hello"),
        (2, "assistant", None, "done: [from: user] hello"),
    ]
    assert chat["pending"] == [] and chat["summary"] is None
    detail = (await client.get(f"/api/tasks/{task_id}", headers=A)).json()
    assert [i["agent"] for i in detail["invocations"]] == ["data"]
    assert [t["id"] for t in (await client.get("/api/tasks", headers=A)).json()] == [task_id]
    # Bob sees none of it.
    assert (await client.get("/api/agents/data/messages", headers=B)).json()["messages"] == []
    assert (await client.get(f"/api/tasks/{task_id}", headers=B)).status_code == 404
    assert (await client.post(f"/api/tasks/{task_id}/cancel", headers=B)).status_code == 404
    r = await client.post(f"/api/tasks/{task_id}/cancel", headers=A)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "task_finished")


async def test_messages_page_backwards_by_seq(client: httpx.AsyncClient) -> None:
    for i in range(3):
        task_id = (await client.post("/api/agents/data/messages", json={"content": f"m{i}"}, headers=A)).json()["task_id"]
        await wait_for(lambda: _task_status(client, task_id))
    newest = (await client.get("/api/agents/data/messages?limit=4", headers=A)).json()["messages"]
    assert [m["seq"] for m in newest] == [3, 4, 5, 6]
    older = (await client.get("/api/agents/data/messages?limit=4&before_seq=3", headers=A)).json()["messages"]
    assert [m["seq"] for m in older] == [1, 2]
    assert (await client.get("/api/agents/data/messages?limit=201", headers=A)).status_code == 422


async def test_pending_lists_queued_inbound_messages(client: httpx.AsyncClient, fake_agents: dict[str, FakeAgent]) -> None:
    gate = asyncio.Event()

    async def slow(s: Session) -> None:
        await gate.wait()
        await s.final("ok")

    fake_agents["data"].handler = slow
    first = (await client.post("/api/agents/data/messages", json={"content": "one"}, headers=A)).json()
    second = (await client.post("/api/agents/data/messages", json={"content": "two"}, headers=A)).json()
    chat = (await client.get("/api/agents/data/messages", headers=A)).json()
    assert [(p["invocation_id"], p["caller"], p["inbound_text"]) for p in chat["pending"]] == [
        (second["invocation_id"], "user", "two")
    ]
    agents = {a["name"]: a for a in (await client.get("/api/agents", headers=A)).json()}
    assert (agents["data"]["busy"], agents["data"]["queue_len"]) == (True, 1)
    gate.set()
    for t in (first, second):
        await wait_for(lambda t=t: _task_status(client, t["task_id"]))


async def test_agents_come_from_loaded_plugins(client: httpx.AsyncClient) -> None:
    agents = (await client.get("/api/agents", headers=A)).json()
    assert [a["name"] for a in agents] == ["orchestrator", "data", "compare", "insight", "report"]
    assert agents[1] == {"name": "data", "description": "data agent", "busy": False, "queue_len": 0}
    r = await client.get("/api/agents/nobody/messages", headers=A)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "unknown_agent")


async def test_post_message_errors(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/agents/nobody/messages", json={"content": "x"}, headers=A)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "unknown_agent")
    r = await client.post("/api/agents/data/messages", json={"content": "  "}, headers=A)
    assert r.status_code == 422


async def test_artifacts_are_owner_scoped_and_dataset_rows_page(client: httpx.AsyncClient) -> None:
    task_id = (await client.post("/api/agents/data/messages", json={"content": "x"}, headers=A)).json()["task_id"]
    await wait_for(lambda: _task_status(client, task_id))
    inv_id = (await client.get(f"/api/tasks/{task_id}", headers=A)).json()["invocations"][0]["id"]
    artifacts = Artifacts(client.app.state.services.db)  # type: ignore[attr-defined]
    ds = await artifacts.insert_dataset(
        user_id=ALICE,
        invocation_id=inv_id,
        name="n",
        source_sql="SELECT n",
        columns=[{"name": "n", "type": "INTEGER"}],
        rows=[[i] for i in range(5)],
        truncated=False,
    )
    r = await client.get(f"/api/datasets/{ds}?offset=1&limit=2", headers=A)
    body = r.json()
    assert (body["row_count"], body["rows"], body["source_sql"]) == (5, [[1], [2]], "SELECT n")
    assert (await client.get(f"/api/datasets/{ds}", headers=B)).status_code == 404
    report = await artifacts.insert_report(user_id=ALICE, invocation_id=inv_id, title="R", markdown="# hi")
    assert [x["id"] for x in (await client.get("/api/reports", headers=A)).json()] == [report]
    assert (await client.get("/api/reports", headers=B)).json() == []
    assert (await client.get(f"/api/reports/{report}", headers=B)).status_code == 404
    assert (await client.get(f"/api/reports/{report}", headers=A)).json()["markdown"] == "# hi"
