"""`ArtifactService`: the one artifact entry point of both transports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from conftest import ALICE, BOB, NOW, migrated_database, seed_users
from vdagent_backend.artifacts import ArtifactError, ArtifactService, ChartError
from vdagent_backend.warehouse import QueryResult

COLUMNS = [{"name": "region", "type": "TEXT"}, {"name": "revenue", "type": "REAL"}]
ROWS = [["North", 10.0], ["South", None], ["East", 2.5], ["West", 7]]
INV = {ALICE: "inv_alice00001", BOB: "inv_bob0000001"}


@pytest.fixture
async def service(tmp_path: Path) -> AsyncIterator[ArtifactService]:
    path = str(tmp_path / "backend.db")
    db = await migrated_database(path)
    seed_users(path)
    async with db.begin() as conn:
        for user, inv in INV.items():
            await conn.exec_driver_sql(
                "INSERT INTO tasks (id, user_id, root_agent, status, created_at) VALUES (?, ?, 'data', 'running', ?)",
                (f"t_{user}", user, NOW),
            )
            await conn.exec_driver_sql(
                "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, created_at)"
                " VALUES (?, ?, ?, 'data', 'user', 0, 'x', 'running', ?)",
                (inv, f"t_{user}", user, NOW),
            )
    yield ArtifactService(db)
    await db.dispose()


async def _store(service: ArtifactService, user: str = ALICE) -> str:
    return await service.store_dataset(user, INV[user], "sales", "SELECT *", QueryResult(COLUMNS, ROWS, truncated=False))


@pytest.mark.parametrize(
    ("offset", "limit", "rows"),
    [(0, 2, ROWS[:2]), (2, 2, ROWS[2:]), (3, 5, ROWS[3:]), (4, 1, []), (100, 1, [])],
    ids=["first", "exact-end", "past-end", "at-row-count", "far-beyond"],
)
async def test_dataset_page_returns_metadata_and_the_requested_rows(
    service: ArtifactService, offset: int, limit: int, rows: list[list[object]]
) -> None:
    ds = await _store(service)
    page = await service.dataset_page(ALICE, ds, offset, limit)
    assert page is not None
    assert (page["id"], page["name"], page["columns"], page["row_count"], page["truncated"], page["source_sql"]) == (
        ds, "sales", COLUMNS, 4, False, "SELECT *"
    )  # fmt: skip
    assert page["rows"] == rows


async def test_reads_of_another_users_or_unknown_artifacts_are_none(service: ArtifactService) -> None:
    ds = await _store(service)
    report = await service.save_report(ALICE, INV[ALICE], "R", f"{{{{dataset:{ds}}}}}")
    for user, dataset_id in ((BOB, ds), (ALICE, "ds_unknown0000")):
        assert await service.dataset_page(user, dataset_id, 0, 10) is None
        assert await service.describe_dataset(user, dataset_id) is None
        assert await service.get_dataset(user, dataset_id) is None
    assert await service.get_report(BOB, report) is None
    assert await service.list_reports(BOB) == []


async def test_describe_dataset_reports_min_max_and_null_count_per_column(service: ArtifactService) -> None:
    ds = await _store(service)
    described = await service.describe_dataset(ALICE, ds)
    assert described is not None
    assert described["columns"] == [
        {"name": "region", "type": "TEXT", "min": "East", "max": "West", "null_count": 0},
        {"name": "revenue", "type": "REAL", "min": 2.5, "max": 10.0, "null_count": 1},
    ]


async def test_datasets_names_the_first_missing_id(service: ArtifactService) -> None:
    ds = await _store(service)
    foreign = await _store(service, BOB)
    assert [d["id"] for d in await service.datasets(ALICE, [ds])] == [ds]
    with pytest.raises(ArtifactError, match=f"^dataset not found: {foreign}$"):
        await service.datasets(ALICE, [ds, foreign, "ds_unknown0000"])


async def test_save_report_rejects_embeds_of_unknown_or_foreign_ids(service: ArtifactService) -> None:
    mine, foreign = await _store(service), await _store(service, BOB)
    chart = await service.create_chart(ALICE, INV[ALICE], mine, "bar", "region", ["revenue"], "Revenue")
    assert chart is not None
    markdown = f"{{{{chart:{chart}}}}}\n{{{{dataset:{mine}}}}}\n{{{{dataset:{foreign}}}}}\n{{{{chart:ch_nope00000000}}}}"
    with pytest.raises(ArtifactError, match=f"^markdown references unknown ids: ch_nope00000000, {foreign}$"):
        await service.save_report(ALICE, INV[ALICE], "R", markdown)
    assert await service.list_reports(ALICE) == []


async def test_create_chart_needs_an_owned_dataset_and_valid_columns(service: ArtifactService) -> None:
    ds = await _store(service)
    assert await service.create_chart(BOB, INV[BOB], ds, "bar", "region", ["revenue"], "T") is None
    with pytest.raises(ChartError, match="y columns must be numeric: region"):
        await service.create_chart(ALICE, INV[ALICE], ds, "bar", "revenue", ["region"], "T")
    chart = await service.create_chart(ALICE, INV[ALICE], ds, "pie", "region", ["revenue"], "Share")
    stored = await service.get_chart(ALICE, chart or "")
    assert stored is not None and stored["spec"]["mark"]["type"] == "arc" and stored["dataset_id"] == ds
