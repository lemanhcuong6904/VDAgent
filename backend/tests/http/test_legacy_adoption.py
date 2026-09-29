"""A backend.db from before Alembic is adopted at startup and served unchanged through the API."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ALICE, LEGACY_DATASET, LEGACY_TASK, FakeAgent, app_client, build_legacy_db, install_plugin, make_config

A = {"X-User-Id": ALICE}


async def test_a_pre_alembic_database_is_served_after_startup(
    tmp_path: Path, fake_agents: dict[str, FakeAgent], monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = make_config(tmp_path, plugins=[install_plugin(monkeypatch, "fake_agents_plugin", fake_agents)])
    build_legacy_db(cfg.backend_db)

    async with app_client(cfg) as client:
        assert [u["name"] for u in (await client.get("/api/users")).json()] == ["Alice", "Bob"]

        (task,) = (await client.get("/api/tasks", headers=A)).json()
        assert (task["id"], task["status"], task["finished_at"]) == (LEGACY_TASK, "completed", "2026-09-24T08:00:01.000Z")
        assert task["created_at"].endswith("Z") and len(task["created_at"]) == 24
        detail = (await client.get(f"/api/tasks/{LEGACY_TASK}", headers=A)).json()
        assert [(i["agent"], i["result_text"]) for i in detail["invocations"]] == [("data", "done")]

        chat = (await client.get("/api/agents/data/messages", headers=A)).json()
        assert [(m["seq"], m["role"], m["content"]) for m in chat["messages"]] == [
            (1, "user", "sales?"),
            (2, "assistant", ""),
            (3, "tool", "rows"),
            (4, "assistant", "done"),
        ]
        assert chat["messages"][1]["tool_calls"] == [{"id": "c1", "name": "send_to_agent", "arguments_json": "{}"}]
        assert chat["messages"][0]["compacted"] is False

        dataset = (await client.get(f"/api/datasets/{LEGACY_DATASET}?offset=1&limit=5", headers=A)).json()
        assert (dataset["row_count"], dataset["rows"], dataset["truncated"]) == (3, [[1], [2]], False)
