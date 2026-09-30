"""Store-level acceptance on a copy of the stack's backend.db (F-01, F-02, F-08): hashes, lineage, evidence."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import golden_task, need, save
from vdagent_backend.db.artifact_store import _envelope, verify  # pyright: ignore[reportPrivateUsage]
from vdagent_contracts.vega_lite import validate_vega_lite


@pytest.fixture(scope="module")
def store() -> dict[str, Any]:
    conn = sqlite3.connect(need("WS7_DB"))
    conn.row_factory = sqlite3.Row
    task = golden_task()
    rows = conn.execute("SELECT * FROM artifacts WHERE run_id = ? ORDER BY artifact_id, version", (task,)).fetchall()
    envs = {(r["artifact_id"], r["version"]): _envelope(SimpleNamespace(**dict(r))) for r in rows}
    latest: dict[str, Any] = {}
    for (aid, _), env in sorted(envs.items()):
        latest[aid] = env
    reports = conn.execute("SELECT id, user_id FROM reports").fetchall()
    return {"envs": envs, "latest": latest, "reports": [dict(r) for r in reports], "conn": conn}


def _ptr(doc: Any, pointer: str) -> Any:
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        doc = doc[int(token)] if isinstance(doc, list) else doc[token]
    return doc


def _resolves(envs: dict[Any, Any], source_ref: str, exact: str) -> bool:
    ref, pointer = source_ref.split("#", 1)
    aid, version = ref.split("@")
    env = envs.get((aid, int(version)))
    return env is not None and str(_ptr(env.payload, pointer)) == exact


def of_type(store: dict[str, Any], kind: str) -> list[Any]:
    return [e for e in store["latest"].values() if e.artifact_type.value == kind]


def test_every_version_verifies_against_its_stored_hash(store: dict[str, Any]) -> None:
    results = {f"{a}@{v}": verify(e) for (a, v), e in store["envs"].items()}
    save("hash_verification.json", {k: {"ok": ok, "status_at_write": s} for k, (ok, s) in results.items()})
    assert results and all(ok for ok, _ in results.values()), [k for k, (ok, _) in results.items() if not ok]
    superseded = [k for (a, v), e in store["envs"].items() if e.status.value == "SUPERSEDED" for k in [f"{a}@{v}"]]
    assert superseded, "run_state history (SUPERSEDED versions) must exist and verify"  # F-02


def test_one_snapshot_one_semantic_version_one_dataset(store: dict[str, Any]) -> None:
    envs = store["envs"].values()
    assert {tuple(e.snapshot_refs) for e in envs} == {("SNAP-2026-09-28",)}
    assert {e.semantic_config_version for e in envs} == {"sc-1"}
    assert len(of_type(store, "dataset")) == 1
    counts = Counter(e.artifact_type.value for e in store["latest"].values())
    save("artifact_types.json", counts)
    assert counts["chart_spec"] == 5 and counts["report"] == 1 and counts["comparison"] == 1


def test_lineage_reaches_the_dataset_through_pinned_hashes(store: dict[str, Any]) -> None:
    envs, dataset = store["envs"], of_type(store, "dataset")[0]

    def reaches(env: Any) -> bool:
        if env.artifact_type.value == "dataset":
            return env.artifact_id == dataset.artifact_id
        found = False
        for ref in env.input_artifact_refs:
            src = envs.get((ref.artifact_id, ref.version))
            assert src is not None, f"dangling {ref.artifact_id}@{ref.version}"
            assert not ref.content_hash or ref.content_hash == src.content_hash
            found = found or reaches(src)
        return found

    assert all(reaches(e) for e in store["latest"].values() if e.artifact_type.value != "run_state")


def test_comparison_values_and_peers(store: dict[str, Any]) -> None:
    [cmp] = of_type(store, "comparison")
    metrics = {m["metric"]: m for m in cmp.payload["metrics"]}
    assert (metrics["dom"]["subjectValue"], metrics["dom"]["benchmark"]["value"]) == (138, 61)
    price = metrics["net_asking_price_per_m2"]
    assert (price["subjectValue"], price["benchmark"]["value"]) == (72500000, 64500000)
    assert Decimal(str(price["pctGap"])) == Decimal("12.40")
    [peer_def] = of_type(store, "peer_definition")
    assert len(peer_def.payload["peers"]) == 5  # B-11: the approved 7-peer rule is still BLOCKED


def test_charts_are_renderable_and_bound_to_evidence(store: dict[str, Any]) -> None:
    charts = of_type(store, "chart_spec")
    problems = {c.artifact_id: validate_vega_lite(c.payload["vega_lite"]) for c in charts}
    assert all(not p for p in problems.values()), problems  # F-01
    bindings = [b for c in charts for b in c.payload["bindings"]]
    assert bindings and all(_resolves(store["envs"], b["source_ref"], b["value_exact"]) for b in bindings)
    assert all("VHop" not in json.dumps(c.payload, ensure_ascii=False) for c in charts)  # F-09


def test_report_statements_are_traceable(store: dict[str, Any]) -> None:
    [report] = of_type(store, "report")
    statements = report.payload["statements"]
    save("report_statements.json", statements)
    assert len(statements) == 28
    assert all(_resolves(store["envs"], s["source_ref"], s["value_exact"]) for s in statements)
    delivered = report.payload["delivery"]["report_id"]
    assert any(r["id"] == delivered and r["user_id"] == report.user_id for r in store["reports"])


def test_no_out_of_scope_data_or_counts(store: dict[str, Any]) -> None:
    blob = json.dumps([e.payload for e in store["latest"].values()], ensure_ascii=False)
    assert "PRJ-Y" not in blob and "D12-09" not in blob
    assert "hidden_rows" not in blob  # F-08
