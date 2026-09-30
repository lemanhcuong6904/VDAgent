"""Artifact Store in backend.db (D5, DEC-022): immutable, versioned envelopes owned by one user.

Reads are scoped by user (I4): another user's artifact reads exactly like an unknown id. The store, not the
producer, assigns `artifact_id`, `version`, `content_hash` and `created_at`.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from vdagent_backend.ids import new_id, now_iso
from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.envelope import ArtifactDraft, ArtifactEnvelope, ArtifactStatus

_COLUMNS = (
    "artifact_id, version, run_id, task_id, user_id, artifact_type, schema_version, status, producer_json,"
    " content_hash, snapshot_refs_json, semantic_config_version, source_refs_json, input_refs_json,"
    " evidence_refs_json, limitations_json, reason_code, reason, payload_json, created_at"
)


def _envelope(row: Any) -> ArtifactEnvelope:
    return ArtifactEnvelope.model_validate(
        {
            "artifact_id": row.artifact_id,
            "version": row.version,
            "run_id": row.run_id,
            "task_id": row.task_id,
            "user_id": row.user_id,
            "artifact_type": row.artifact_type,
            "schema_version": row.schema_version,
            "status": row.status,
            "producer": json.loads(row.producer_json),
            "content_hash": row.content_hash,
            "snapshot_refs": json.loads(row.snapshot_refs_json),
            "semantic_config_version": row.semantic_config_version,
            "source_refs": json.loads(row.source_refs_json),
            "input_artifact_refs": json.loads(row.input_refs_json),
            "evidence_refs": json.loads(row.evidence_refs_json),
            "limitations": json.loads(row.limitations_json),
            "reason_code": row.reason_code,
            "reason": row.reason,
            "payload": json.loads(row.payload_json),
            "created_at": row.created_at,
        }
    )


async def _check_inputs(conn: AsyncConnection, user_id: str, draft: ArtifactDraft) -> None:
    """Every input ref names a stored version of this user, of the stated type and, when pinned, hash (WS1).

    Snapshot and semantic config version must agree between the draft and its inputs wherever both declare one;
    an artifact that declares none (a legacy artifact) is not compared.
    """
    snapshots = {tuple(draft.snapshot_refs)} if draft.snapshot_refs else set()
    semantics = {draft.semantic_config_version} if draft.semantic_config_version else set()
    for ref in draft.input_artifact_refs:
        row = (
            await conn.execute(
                text(
                    "SELECT artifact_type, content_hash, snapshot_refs_json, semantic_config_version FROM artifacts"
                    " WHERE artifact_id = :id AND version = :version AND user_id = :user_id"
                ),
                {"id": ref.artifact_id, "version": ref.version, "user_id": user_id},
            )
        ).first()
        label = f"{ref.artifact_id}@{ref.version}"
        if row is None:
            raise ValueError(f"unknown input artifact {label}")
        if row.artifact_type != ref.artifact_type.value:
            raise ValueError(f"input artifact {label} is {row.artifact_type}, not {ref.artifact_type.value}")
        if ref.content_hash is not None and ref.content_hash != row.content_hash:
            raise ValueError(f"input artifact {label}: content hash does not match the stored version")
        if row_snapshots := json.loads(row.snapshot_refs_json):
            snapshots.add(tuple(row_snapshots))
        if row.semantic_config_version:
            semantics.add(row.semantic_config_version)
    if len(snapshots) > 1:
        raise ValueError(f"inputs and artifact disagree on the snapshot: {sorted(snapshots)}")
    if len(semantics) > 1:
        raise ValueError(f"inputs and artifact disagree on semantic_config_version: {sorted(semantics)}")


async def put(db: AsyncEngine, *, user_id: str, run_id: str, task_id: str, draft: ArtifactDraft) -> ArtifactEnvelope:
    """Store a draft as version 1 of a new artifact, or as the next version of `draft.artifact_id`.

    Raises ValueError for a float in the payload, for a new version of an artifact that is unknown to this
    user or of another type, or for input refs that fail `_check_inputs`. A rejected draft writes nothing.
    """
    try:
        payload_json = canonical_json(draft.payload)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc
    async with db.begin() as conn:
        await _check_inputs(conn, user_id, draft)
        if draft.artifact_id is None:
            artifact_id, version = new_id("art"), 1
        else:
            artifact_id = draft.artifact_id
            prev = (
                await conn.execute(
                    text(
                        "SELECT MAX(version) AS last_version, MIN(artifact_type) AS kind FROM artifacts"
                        " WHERE artifact_id = :id AND user_id = :user_id"
                    ),
                    {"id": artifact_id, "user_id": user_id},
                )
            ).one()
            if prev.last_version is None:
                raise ValueError(f"unknown artifact {artifact_id}")
            if prev.kind != draft.artifact_type.value:
                raise ValueError("a new version keeps the artifact type")
            version = prev.last_version + 1
            await conn.execute(
                text("UPDATE artifacts SET status = 'SUPERSEDED' WHERE artifact_id = :id AND status <> 'SUPERSEDED'"),
                {"id": artifact_id},
            )
        created_at = now_iso()
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
            text(
                f"INSERT INTO artifacts ({_COLUMNS}) VALUES (:artifact_id, :version, :run_id, :task_id, :user_id,"
                " :artifact_type, :schema_version, :status, :producer_json, :content_hash, :snapshot_refs_json,"
                " :semantic_config_version, :source_refs_json, :input_refs_json, :evidence_refs_json,"
                " :limitations_json, :reason_code, :reason, :payload_json, :created_at)"
            ),
            {
                "artifact_id": artifact_id,
                "version": version,
                "run_id": run_id,
                "task_id": task_id,
                "user_id": user_id,
                "artifact_type": envelope.artifact_type.value,
                "schema_version": envelope.schema_version,
                "status": envelope.status.value,
                "producer_json": canonical_json(envelope.producer),
                "content_hash": envelope.compute_content_hash(),
                "snapshot_refs_json": canonical_json(envelope.snapshot_refs),
                "semantic_config_version": envelope.semantic_config_version,
                "source_refs_json": canonical_json(envelope.source_refs),
                "input_refs_json": canonical_json(envelope.input_artifact_refs),
                "evidence_refs_json": canonical_json(envelope.evidence_refs),
                "limitations_json": canonical_json(envelope.limitations),
                "reason_code": envelope.reason_code,
                "reason": envelope.reason,
                "payload_json": payload_json,
                "created_at": created_at,
            },
        )
    stored = await get(db, user_id, artifact_id, version=version)
    assert stored is not None
    return stored


async def get(db: AsyncEngine, user_id: str, artifact_id: str, *, version: int | None = None) -> ArtifactEnvelope | None:
    """One version (the latest when `version` is None), or None if unknown to this user."""
    sql = f"SELECT {_COLUMNS} FROM artifacts WHERE artifact_id = :id AND user_id = :user_id"
    params: dict[str, Any] = {"id": artifact_id, "user_id": user_id}
    if version is not None:
        sql += " AND version = :version"
        params["version"] = version
    sql += " ORDER BY version DESC LIMIT 1"
    async with db.connect() as conn:
        row = (await conn.execute(text(sql), params)).first()
    return None if row is None else _envelope(row)


async def list_artifacts(
    db: AsyncEngine, user_id: str, *, run_id: str | None = None, artifact_type: str | None = None
) -> list[ArtifactEnvelope]:
    """Latest version of each of this user's artifacts, oldest first, optionally filtered (DEC-024)."""
    sql = (
        f"SELECT {_COLUMNS} FROM artifacts a WHERE user_id = :user_id"
        " AND version = (SELECT MAX(version) FROM artifacts b WHERE b.artifact_id = a.artifact_id)"
    )
    params: dict[str, Any] = {"user_id": user_id}
    if run_id is not None:
        sql += " AND run_id = :run_id"
        params["run_id"] = run_id
    if artifact_type is not None:
        sql += " AND artifact_type = :artifact_type"
        params["artifact_type"] = artifact_type
    sql += " ORDER BY created_at, artifact_id"
    async with db.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()
    return [_envelope(row) for row in rows]


_WRITABLE_STATUSES = ("VALID", "PARTIAL", "INVALID", "DRAFT")


def verify(envelope: ArtifactEnvelope) -> tuple[bool, str | None]:
    """Re-verify a stored envelope against its stored `content_hash` (WS7 F-02).

    The hash covers the status an artifact was written with; the store's only update later sets SUPERSEDED. A
    superseded version is therefore checked against each status a writer may submit: exactly the original one
    matches. Returns (verified, status at write time); nothing stored is rewritten.
    """
    if envelope.status.value != "SUPERSEDED":
        ok = envelope.compute_content_hash() == envelope.content_hash
        return ok, envelope.status.value if ok else None
    for status in _WRITABLE_STATUSES:
        candidate = envelope.model_copy(update={"status": ArtifactStatus(status)})
        if candidate.compute_content_hash() == envelope.content_hash:
            return True, status
    return False, None
