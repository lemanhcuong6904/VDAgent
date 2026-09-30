"""Artifact Store (D5): immutable envelopes, versioning with SUPERSEDED, user-scoped reads."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from conftest import ALICE, BOB, seed_users
from vdagent_backend.db import artifact_store
from vdagent_backend.db.database import create_db
from vdagent_contracts.envelope import ArtifactDraft, ArtifactEnvelope, ArtifactStatus


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Any]:
    path = str(tmp_path / "backend.db")
    engine = create_db(path)
    seed_users(path)
    yield engine
    await engine.dispose()


def _draft(**overrides: Any) -> ArtifactDraft:
    fields: dict[str, Any] = {
        "artifact_type": "data_package",
        "schema_version": "data_package@1",
        "status": "VALID",
        "producer": {"agent": "data", "agent_version": "0.1.0"},
        "snapshot_refs": ["SNAP-1"],
        "semantic_config_version": "sc-1",
        "payload": {"median": Decimal("64500000.00"), "n": 7},
    }
    fields.update(overrides)
    return ArtifactDraft.model_validate(fields)


async def _put(db: Any, draft: ArtifactDraft | None = None, *, user: str = ALICE, run: str = "t_1") -> ArtifactEnvelope:
    return await artifact_store.put(db, user_id=user, run_id=run, task_id=run, draft=draft or _draft())


async def test_put_returns_id_and_version_1(db: Any) -> None:
    stored = await _put(db)
    assert stored.artifact_id.startswith("art_")
    assert stored.version == 1
    assert stored.status is ArtifactStatus.VALID
    assert stored.created_at is not None
    again = await artifact_store.get(db, ALICE, stored.artifact_id)
    assert again == stored
    assert again is not None and again.payload["median"] == "64500000.00"  # Decimal travels as a string


async def test_put_same_id_new_version_supersedes_old(db: Any) -> None:
    first = await _put(db)
    second = await _put(db, _draft(artifact_id=first.artifact_id, payload={"median": "65000000", "n": 7}))
    assert second.artifact_id == first.artifact_id and second.version == 2
    old = await artifact_store.get(db, ALICE, first.artifact_id, version=1)
    assert old is not None and old.status is ArtifactStatus.SUPERSEDED
    latest = await artifact_store.get(db, ALICE, first.artifact_id)
    assert latest == second
    with pytest.raises(ValueError):  # another user cannot version my artifact
        await _put(db, _draft(artifact_id=first.artifact_id), user=BOB)
    with pytest.raises(ValueError):  # nor change its type
        await _put(db, _draft(artifact_id=first.artifact_id, artifact_type="insight"))


async def test_artifact_immutable_update_rejected(db: Any) -> None:
    stored = await _put(db)
    with sqlite3.connect(db.url.database) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE artifacts SET payload_json = '{}' WHERE artifact_id = ?", (stored.artifact_id,))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM artifacts WHERE artifact_id = ?", (stored.artifact_id,))


async def test_get_other_user_returns_none(db: Any) -> None:
    stored = await _put(db)
    assert await artifact_store.get(db, BOB, stored.artifact_id) is None
    assert await artifact_store.get(db, ALICE, "art_missing") is None
    assert await artifact_store.list_artifacts(db, BOB) == []


async def test_list_filters_by_run_and_type(db: Any) -> None:
    a = await _put(db, run="t_1")
    await _put(db, _draft(artifact_type="insight", producer={"agent": "insight", "agent_version": "0.1.0"}), run="t_1")
    await _put(db, run="t_2")
    await _put(db, _draft(artifact_id=a.artifact_id), run="t_1")  # v2 of a: listed once, latest only
    run1 = await artifact_store.list_artifacts(db, ALICE, run_id="t_1")
    assert sorted(e.artifact_type for e in run1) == ["data_package", "insight"]
    assert [e.version for e in run1 if e.artifact_id == a.artifact_id] == [2]
    packages = await artifact_store.list_artifacts(db, ALICE, artifact_type="data_package")
    assert len(packages) == 2


async def test_content_hash_computed_server_side_matches_contracts(db: Any) -> None:
    draft = _draft()
    first = await _put(db, draft, run="t_1")
    second = await _put(db, draft, run="t_9")
    assert first.content_hash == second.content_hash == first.compute_content_hash()
    with pytest.raises(ValueError):
        await _put(db, _draft(payload={"ratio": 0.68}))  # floats never enter the store


# ---- WS1: strict input references (docs/integration/CANONICAL_DATA_CONTRACT.md §3, §6) ----


def _ref(stored: ArtifactEnvelope, **overrides: Any) -> dict[str, Any]:
    ref: dict[str, Any] = {"artifact_id": stored.artifact_id, "version": stored.version, "artifact_type": stored.artifact_type.value}
    ref.update(overrides)
    return ref


def _consumer(*refs: dict[str, Any], **overrides: Any) -> ArtifactDraft:
    return _draft(
        artifact_type="comparison", schema_version="comparison@1",
        producer={"agent": "compare", "agent_version": "0.1.0"},
        input_artifact_refs=list(refs), **overrides,
    )


async def test_put_accepts_resolvable_input_refs_with_matching_hash(db: Any) -> None:
    source = await _put(db)
    stored = await _put(db, _consumer(_ref(source, content_hash=source.content_hash)))
    assert stored.input_artifact_refs[0].artifact_id == source.artifact_id
    assert stored.input_artifact_refs[0].content_hash == source.content_hash


async def test_put_rejects_unknown_input_ref(db: Any) -> None:
    with pytest.raises(ValueError, match="unknown input artifact art_missing@1"):
        await _put(db, _consumer({"artifact_id": "art_missing", "version": 1, "artifact_type": "data_package"}))


async def test_put_rejects_input_ref_of_another_user(db: Any) -> None:
    theirs = await _put(db, user=BOB)
    with pytest.raises(ValueError, match="unknown input artifact"):
        await _put(db, _consumer(_ref(theirs)))


async def test_put_rejects_unknown_input_version(db: Any) -> None:
    source = await _put(db)
    with pytest.raises(ValueError, match="unknown input artifact"):
        await _put(db, _consumer(_ref(source, version=2)))


async def test_put_rejects_input_ref_with_wrong_type(db: Any) -> None:
    source = await _put(db)
    with pytest.raises(ValueError, match="is data_package, not dataset"):
        await _put(db, _consumer(_ref(source, artifact_type="dataset")))


async def test_put_rejects_input_ref_hash_mismatch(db: Any) -> None:
    source = await _put(db)
    with pytest.raises(ValueError, match="content hash"):
        await _put(db, _consumer(_ref(source, content_hash="0" * 64)))


async def test_put_pins_superseded_versions(db: Any) -> None:
    first = await _put(db)
    await _put(db, _draft(artifact_id=first.artifact_id, payload={"median": "65000000", "n": 7}))
    stored = await _put(db, _consumer(_ref(first, content_hash=first.content_hash)))  # v1 stays readable and pinnable
    assert stored.input_artifact_refs[0].version == 1


async def test_put_rejects_snapshot_mismatch_with_input(db: Any) -> None:
    source = await _put(db, _draft(snapshot_refs=["SNAP-2026-08-31"]))
    with pytest.raises(ValueError, match="snapshot"):
        await _put(db, _consumer(_ref(source), snapshot_refs=["SNAP-2026-09-28"]))


async def test_put_rejects_semantic_version_mismatch_with_input(db: Any) -> None:
    source = await _put(db, _draft(semantic_config_version="3.1.0"))
    with pytest.raises(ValueError, match="semantic_config_version"):
        await _put(db, _consumer(_ref(source), semantic_config_version="sc-1"))


async def test_put_rejects_inputs_that_disagree_with_each_other(db: Any) -> None:
    a = await _put(db, _draft(snapshot_refs=["SNAP-2026-08-31"]))
    b = await _put(db, _draft(snapshot_refs=["SNAP-2026-09-28"]))
    with pytest.raises(ValueError, match="snapshot"):
        await _put(db, _consumer(_ref(a), _ref(b), snapshot_refs=[]))


async def test_put_legacy_artifacts_without_snapshot_or_refs_still_work(db: Any) -> None:
    legacy = await _put(db, _draft(snapshot_refs=[], semantic_config_version=None))
    stored = await _put(db, _consumer(_ref(legacy)))  # nothing declared on the input: nothing to compare
    assert stored.version == 1


async def test_put_rejected_draft_writes_nothing(db: Any) -> None:
    with pytest.raises(ValueError):
        await _put(db, _consumer({"artifact_id": "art_missing", "version": 1, "artifact_type": "data_package"}))
    assert await artifact_store.list_artifacts(db, ALICE) == []


async def test_decimal_payload_round_trips_exactly(db: Any) -> None:
    stored = await _put(db, _draft(payload={"net_area_m2": Decimal("63.02"), "ratio": Decimal("0.10"), "vnd": 72500000}))
    assert stored.payload == {"net_area_m2": "63.02", "ratio": "0.10", "vnd": 72500000}
