"""S0 intake (build spec 02 §5, R-03, R-06, D8): validate the StepSpec, dedupe on its idempotency key, lock the
snapshot and its semantic_config version, and take the user's scope from the Backend — never from the message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from vdagent_agentkit.mcp_client import McpSession
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.scope import AuthorizedScope, UserContext
from vdagent_data.specs import OPERATIONS, CommonSpec


@dataclass(frozen=True)
class Failure:
    code: str  # a Data catalog error code
    reason: str


@dataclass(frozen=True)
class Intake:
    step: StepSpec
    spec: CommonSpec
    snapshot_id: str
    snapshot_key: int
    snapshot_date: str
    semantic_config_version: str
    config: dict[str, Any]
    scope: AuthorizedScope
    reused: dict[str, Any] | None = None
    sql_runs: int = field(default=0)
    snapshot_loaded_at: str | None = None


async def _tool(session: McpSession, name: str, args: dict[str, Any]) -> Any:
    outcome = await session.call_tool(name, args)
    if outcome.is_error:
        raise RuntimeError(outcome.text)
    return json.loads(outcome.text)


async def _rows(session: McpSession, sql: str) -> list[list[Any]]:
    result = await _tool(session, "re_run_query", {"sql": sql})
    rows: list[list[Any]] = list(result["preview"])
    while len(rows) < result["row_count"]:
        page = await _tool(session, "get_dataset_rows", {"dataset_id": result["dataset_id"], "offset": len(rows), "limit": 200})
        rows.extend(page["rows"])
    return rows


async def _reused(session: McpSession, step: StepSpec) -> dict[str, Any] | None:
    listed = await _tool(session, "artifact_list", {"run_id": step.run_id, "artifact_type": "data_package"})
    for summary in listed["artifacts"]:
        envelope = await _tool(session, "artifact_get", {"artifact_id": summary["artifact_id"]})
        if envelope["payload"].get("idempotency_key") == step.idempotency_key:
            return envelope
    return None


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def intake(step: StepSpec, session: McpSession, *, user_id: str) -> Intake | Failure:
    """`user_id` is the invoking user (ctx.user_id); the StepSpec's user_context must belong to it."""
    model = OPERATIONS.get(step.operation)
    if model is None:
        return Failure("OUT_OF_SCOPE", f"Thao tác {step.operation!r} không thuộc 4 thao tác của Data Agent.")
    try:
        spec = model.model_validate(step.spec)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return Failure("SPEC_MISMATCH", f"StepSpec không hợp lệ: {details}")

    context = UserContext.model_validate(await _tool(session, "get_user_context", {}))
    if step.user_context.user_id != user_id or context.user_id != user_id:
        return Failure("OUT_OF_SCOPE", "Yêu cầu không thuộc quyền của người dùng hiện tại.")
    scope = context.authorized_scope
    if not scope.project_ids and not scope.zone_ids:
        return Failure("OUT_OF_SCOPE", "Người dùng chưa được cấp quyền xem dữ liệu nào.")

    reused = await _reused(session, step)

    manifest = await _rows(
        session,
        "SELECT snapshot_id, snapshot_date_key, status, semantic_config_version, loaded_at FROM snapshot_manifest"
        " ORDER BY snapshot_date_key",
    )
    approved = [r for r in manifest if r[2] == "APPROVED"]
    if step.snapshot_id is None:
        if not approved:
            return Failure("DQ_BLOCKING", "Chưa có snapshot nào được duyệt (APPROVED).")
        chosen = approved[-1]
    else:
        match = [r for r in approved if r[0] == step.snapshot_id]
        if not match:
            return Failure("DQ_BLOCKING", f"Snapshot {step.snapshot_id} không tồn tại hoặc chưa được duyệt.")
        chosen = match[0]
    snapshot_id, snapshot_key, _status, version, loaded_at = chosen
    if step.semantic_config_version is not None and step.semantic_config_version != version:
        return Failure(
            "DQ_BLOCKING",
            f"semantic_config_version {step.semantic_config_version} lệch với snapshot {snapshot_id} ({version}).",
        )
    config_rows = await _rows(
        session, f"SELECT config_key, config_value FROM semantic_config WHERE config_version = {_quote(version)}"
    )
    config = {key: json.loads(value) for key, value in config_rows}
    day = str(snapshot_key)
    return Intake(
        step=step, spec=spec, snapshot_id=snapshot_id, snapshot_key=int(snapshot_key),
        snapshot_date=f"{day[:4]}-{day[4:6]}-{day[6:]}", semantic_config_version=version, config=config,
        scope=scope, reused=reused, sql_runs=2, snapshot_loaded_at=loaded_at,
    )
