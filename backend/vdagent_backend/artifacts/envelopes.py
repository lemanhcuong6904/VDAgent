"""`EnvelopeStore`: the artifact envelope store (D5, WS1): immutable, versioned envelopes owned by one user.

Reads are scoped by user: another user's artifact reads exactly like an unknown id. The store, not the producer,
assigns `artifact_id`, `version`, `content_hash` and `created_at`. A new version marks the previous ones SUPERSEDED
(the only update the table's triggers allow). Input references must name stored versions of this user, of the stated
type and, when pinned, hash; snapshot and semantic config version must agree between a draft and its inputs.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from vdagent_backend.artifacts.errors import EnvelopeError
from vdagent_backend.core import iso_ms, new_id, utcnow
from vdagent_backend.persistence import Row, fetch_all, fetch_one, tables
from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.envelope import ArtifactDraft, ArtifactEnvelope, ArtifactStatus

_art = tables.artifacts
_WRITABLE_STATUSES = ("VALID", "PARTIAL", "INVALID", "DRAFT")


def _envelope(row: Row) -> ArtifactEnvelope:
    return ArtifactEnvelope.model_validate(
        {
            "artifact_id": row["artifact_id"],
            "version": row["version"],
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "user_id": row["user_id"],
            "artifact_type": row["artifact_type"],
            "schema_version": row["schema_version"],
            "status": row["status"],
            "producer": json.loads(row["producer_json"]),
            "content_hash": row["content_hash"],
            "snapshot_refs": json.loads(row["snapshot_refs_json"]),
            "semantic_config_version": row["semantic_config_version"],
            "source_refs": json.loads(row["source_refs_json"]),
            "input_artifact_refs": json.loads(row["input_refs_json"]),
            "evidence_refs": json.loads(row["evidence_refs_json"]),
            "limitations": json.loads(row["limitations_json"]),
            "reason_code": row["reason_code"],
            "reason": row["reason"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
    )


def verify_envelope(envelope: ArtifactEnvelope) -> tuple[bool, str | None]:
    """Re-verify a stored envelope against its stored `content_hash` (WS7 F-02).

    The hash covers the status an artifact was written with; the store's only later update sets SUPERSEDED. A
    superseded version is therefore checked against each status a writer may submit: exactly the original matches.
    Returns (verified, status at write time); nothing stored is rewritten.
    """
    if envelope.status is not ArtifactStatus.SUPERSEDED:
        ok = envelope.compute_content_hash() == envelope.content_hash
        return ok, envelope.status.value if ok else None
    for status in _WRITABLE_STATUSES:
        candidate = envelope.model_copy(update={"status": ArtifactStatus(status)})
        if candidate.compute_content_hash() == envelope.content_hash:
            return True, status
    return False, None


async def _check_inputs(conn: AsyncConnection, user_id: str, draft: ArtifactDraft) -> None:
    snapshots = {tuple(draft.snapshot_refs)} if draft.snapshot_refs else set()
    semantics = {draft.semantic_config_version} if draft.semantic_config_version else set()
    for ref in draft.input_artifact_refs:
        row = (
            await conn.execute(
                select(_art.c.artifact_type, _art.c.content_hash, _art.c.snapshot_refs_json, _art.c.semantic_config_version)
                .where(_art.c.artifact_id == ref.artifact_id, _art.c.version == ref.version, _art.c.user_id == user_id)
            )
        ).mappings().first()
        label = f"{ref.artifact_id}@{ref.version}"
        if row is None:
            raise EnvelopeError(f"unknown input artifact {label}")
        if row["artifact_type"] != ref.artifact_type.value:
            raise EnvelopeError(f"input artifact {label} is {row['artifact_type']}, not {ref.artifact_type.value}")
        if ref.content_hash is not None and ref.content_hash != row["content_hash"]:
            raise EnvelopeError(f"input artifact {label}: content hash does not match the stored version")
        if row_snapshots := json.loads(row["snapshot_refs_json"]):
            snapshots.add(tuple(row_snapshots))
        if row["semantic_config_version"]:
            semantics.add(row["semantic_config_version"])
    if len(snapshots) > 1:
        raise EnvelopeError(f"inputs and artifact disagree on the snapshot: {sorted(snapshots)}")
    if len(semantics) > 1:
        raise EnvelopeError(f"inputs and artifact disagree on semantic_config_version: {sorted(semantics)}")


class EnvelopeStore:
    """Repository of the `artifacts` table; every method takes the owning user."""

    def __init__(self, db: AsyncEngine) -> None:
        self._db = db

    async def put(self, *, user_id: str, run_id: str, task_id: str, draft: ArtifactDraft) -> ArtifactEnvelope:
        """Store a draft as version 1 of a new artifact, or as the next version of `draft.artifact_id`.

        Raises:
            EnvelopeError: a float in the payload, a new version of an artifact unknown to this user or of another
                type, or input refs that fail the checks. A rejected draft writes nothing.
        """
        try:
            payload_json = canonical_json(draft.payload)
        except TypeError as exc:
            raise EnvelopeError(str(exc)) from exc
        async with self._db.begin() as conn:
            await _check_inputs(conn, user_id, draft)
            if draft.artifact_id is None:
                artifact_id, version = new_id("art"), 1
            else:
                artifact_id = draft.artifact_id
                prev = (
                    await conn.execute(
                        select(func.max(_art.c.version).label("last"), func.min(_art.c.artifact_type).label("kind"))
                        .where(_art.c.artifact_id == artifact_id, _art.c.user_id == user_id)
                    )
                ).mappings().one()
                if prev["last"] is None:
                    raise EnvelopeError(f"unknown artifact {artifact_id}")
                if prev["kind"] != draft.artifact_type.value:
                    raise EnvelopeError("a new version keeps the artifact type")
                version = prev["last"] + 1
                await conn.execute(
                    _art.update()
                    .where(_art.c.artifact_id == artifact_id, _art.c.status != "SUPERSEDED")
                    .values(status="SUPERSEDED")
                )
            created_at = iso_ms(utcnow())
            envelope = ArtifactEnvelope.model_validate(
                {
                    **draft.model_dump(mode="python", exclude={"artifact_id"}),
                    "payload": json.loads(payload_json),
                    "artifact_id": artifact_id,
                    "version": version,
                    "run_id": run_id,
                    "task_id": task_id,
                    "user_id": user_id,
                    "created_at": created_at,
                }
            )
            await conn.execute(
                _art.insert().values(
                    artifact_id=artifact_id,
                    version=version,
                    run_id=run_id,
                    task_id=task_id,
                    user_id=user_id,
                    artifact_type=envelope.artifact_type.value,
                    schema_version=envelope.schema_version,
                    status=envelope.status.value,
                    producer_json=canonical_json(envelope.producer),
                    content_hash=envelope.compute_content_hash(),
                    snapshot_refs_json=canonical_json(envelope.snapshot_refs),
                    semantic_config_version=envelope.semantic_config_version,
                    source_refs_json=canonical_json(envelope.source_refs),
                    input_refs_json=canonical_json(envelope.input_artifact_refs),
                    evidence_refs_json=canonical_json(envelope.evidence_refs),
                    limitations_json=canonical_json(envelope.limitations),
                    reason_code=envelope.reason_code,
                    reason=envelope.reason,
                    payload_json=payload_json,
                    created_at=created_at,
                )
            )
        stored = await self.get(user_id, artifact_id, version=version)
        assert stored is not None
        return stored

    async def get(self, user_id: str, artifact_id: str, *, version: int | None = None) -> ArtifactEnvelope | None:
        """One version (the latest when `version` is None), or None if unknown to this user."""
        stmt = select(_art).where(_art.c.artifact_id == artifact_id, _art.c.user_id == user_id)
        if version is not None:
            stmt = stmt.where(_art.c.version == version)
        row = await fetch_one(self._db, stmt.order_by(_art.c.version.desc()).limit(1))
        return None if row is None else _envelope(row)

    async def list_artifacts(
        self, user_id: str, *, run_id: str | None = None, artifact_type: str | None = None
    ) -> list[ArtifactEnvelope]:
        """Latest version of each of this user's artifacts, oldest first, optionally filtered (DEC-024)."""
        inner = _art.alias("b")
        stmt = select(_art).where(
            _art.c.user_id == user_id,
            _art.c.version == select(func.max(inner.c.version)).where(inner.c.artifact_id == _art.c.artifact_id).scalar_subquery(),
        )
        if run_id is not None:
            stmt = stmt.where(_art.c.run_id == run_id)
        if artifact_type is not None:
            stmt = stmt.where(_art.c.artifact_type == artifact_type)
        rows = await fetch_all(self._db, stmt.order_by(_art.c.created_at, _art.c.artifact_id))
        return [_envelope(r) for r in rows]
