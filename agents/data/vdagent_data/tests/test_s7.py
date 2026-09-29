"""S7 materialize: data_package manifest, stable content hashes, PII drop, summary numbers ⊆ manifest."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from vdagent_agentkit.testing import FakeMcp
from vdagent_contracts.envelope import ArtifactDraft, ArtifactStatus
from vdagent_data.pipeline.s6_verify import DqResult, compute_metrics
from vdagent_data.pipeline.s7_materialize import (
    PackageEntry,
    build_package,
    numbers_in,
    persist,
    summarize,
    unsupported_numbers,
)

DQ_OK = [DqResult("DQ-DUP-KEY", "PASS")]


def metric_entry() -> PackageEntry:
    rows = [
        {"floor_band": "LOW", "avg_dom_unsold__num": 300, "avg_dom_unsold__den": 5, "n": 5},
        {"floor_band": "MID", "avg_dom_unsold__num": 610, "avg_dom_unsold__den": 10, "n": 10},
    ]
    return PackageEntry.metric_table(
        dataset_id="ds_1", grain="floor_band", group_by=["floor_band"], rows=rows,
        metrics=compute_metrics(rows, ["avg_dom_unsold"]),
    )


def package(**overrides: Any) -> ArtifactDraft:
    fields: dict[str, Any] = {
        "operation": "aggregate_metrics",
        "snapshot_id": "SNAP-2026-09-28",
        "semantic_config_version": "sc-1",
        "resolved": {"Landmark": {"kind": "ZONE", "ids": ["ZN-A"]}},
        "entries": [metric_entry()],
        "dq": DQ_OK,
        "lineage": [{"tier": "T1", "sql_hash": "a" * 64}],
        "summary": "DOM trung bình 60 ngày ở nhóm tầng LOW và 61 ngày ở nhóm MID.",
    }
    fields.update(overrides)
    return build_package(**fields)


def test_package_manifest_schema() -> None:
    draft = package()
    assert draft.artifact_type == "data_package" and draft.status is ArtifactStatus.VALID
    assert draft.snapshot_refs == ["SNAP-2026-09-28"] and draft.semantic_config_version == "sc-1"
    [entry] = draft.payload["artifacts"]
    assert entry["kind"] == "metric_table" and entry["grain"] == "floor_band" and entry["rows"] == 2
    assert len(entry["content_hash"]) == 64 and entry["dataset_id"] == "ds_1"
    assert entry["metrics"][1]["avg_dom_unsold"]["value"] == "61.00"
    assert entry["metrics"][1]["avg_dom_unsold"]["formula_id"] == "F-DOM-01"
    kinds = [a["kind"] for a in draft.payload["artifacts"]]
    assert "dq_report" in {k for k in draft.payload} or kinds  # dq is its own section
    assert draft.payload["dq_report"]["rules"][0]["rule"] == "DQ-DUP-KEY"
    json.dumps(draft.model_dump(mode="json"))  # serialisable for artifact_put


def test_package_content_hash_stable() -> None:
    a, b = package(), package()
    assert a.payload["artifacts"][0]["content_hash"] == b.payload["artifacts"][0]["content_hash"]
    assert a.payload["content_hash"] == b.payload["content_hash"]
    other_run = package(idempotency_key="PLAN-9:B1", summary="Nhóm MID có DOM trung bình 61 ngày.")
    assert other_run.payload["content_hash"] == a.payload["content_hash"]  # run identity and wording are not content
    changed = package(entries=[PackageEntry.metric_table(dataset_id="ds_9", grain="floor_band", group_by=["floor_band"],
                                                         rows=[], metrics=[])])
    assert changed.payload["content_hash"] != a.payload["content_hash"]
    # a small sample or a limitation makes it PARTIAL, never silently VALID
    partial = package(limitations=["SMALL_SAMPLE: nhóm TOP có 2 căn"])
    assert partial.status is ArtifactStatus.PARTIAL


async def test_second_write_new_version() -> None:
    stored: list[dict[str, Any]] = []

    def put(args: dict[str, Any]) -> dict[str, Any]:
        draft = json.loads(args["draft_json"])
        stored.append(draft)
        return {"artifact_id": draft.get("artifact_id") or "art_1", "version": len(stored)}

    mcp = FakeMcp({"artifact_put": put})
    first = await persist(mcp, package())
    second = await persist(mcp, package(), supersedes=first["artifact_id"])
    assert (first["version"], second["version"]) == (1, 2)
    assert stored[1]["artifact_id"] == "art_1" and "artifact_id" not in stored[0]


def test_pii_columns_dropped() -> None:
    entry = PackageEntry.table(kind="unit_set", dataset_id="ds_2", grain="unit",
                               rows=[{"unit_code": "A12-08", "customer_phone": "0909", "owner_name": "X"}])
    assert entry.columns == ["unit_code"] and entry.dropped_pii == ["customer_phone", "owner_name"]
    draft = package(operation="fetch_units", entries=[entry], summary="Có 1 căn.")
    [unit_set] = draft.payload["artifacts"]
    assert unit_set["columns"] == ["unit_code"] and "0909" not in json.dumps(draft.payload)
    assert draft.payload["pii_dropped"] == ["customer_phone", "owner_name"]  # names only, for the audit trail


def test_summary_numbers_subset_of_manifest() -> None:
    assert numbers_in("Giá 64.500.000 VND/m², chênh +12,4%, hạng 8/8, DOM 138 ngày") == [
        Decimal("64500000"), Decimal("12.4"), Decimal("8"), Decimal("8"), Decimal("138")
    ]
    assert numbers_in("snapshot SNAP-2026-09-28, căn A12-08") == []
    draft = package()
    assert unsupported_numbers("DOM trung bình 61 ngày, nhóm LOW 60 ngày, nhóm MID 10 căn.", draft.payload) == []
    assert unsupported_numbers("Tổng 15 căn.", draft.payload) == [Decimal("15")]  # derived totals are not in the package
    assert unsupported_numbers("DOM trung bình 65 ngày.", draft.payload) == [Decimal("65")]


async def test_summary_sensor_retry_then_template() -> None:
    draft = package()
    attempts: list[int] = []

    async def liar(payload: dict[str, Any]) -> str:
        attempts.append(1)
        return "DOM trung bình 99 ngày."

    text, source = await summarize(draft.payload, liar)
    assert source == "TEMPLATE" and len(attempts) == 2
    assert unsupported_numbers(text, draft.payload) == []

    async def honest(payload: dict[str, Any]) -> str:
        return "Nhóm MID có DOM trung bình 61 ngày."

    assert await summarize(draft.payload, honest) == ("Nhóm MID có DOM trung bình 61 ngày.", "LLM")
