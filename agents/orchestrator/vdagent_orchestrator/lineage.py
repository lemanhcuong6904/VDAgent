"""The Orchestrator's own artifacts (backend WRITABLE_TYPES: run_state, run_summary).

`run_state` is written when a run starts: it records the plan (never `user_context`) and anchors the run to the task
that started it, so later turns may keep writing into it (DEC-045). `run_summary` is written once when the run
closes, with every package of the run as `input_artifact_refs` — the root of the run's lineage.
"""

from __future__ import annotations

import json
import logging

from vdagent_agentkit.mcp_client import McpSession
from vdagent_contracts.envelope import ArtifactDraft, ArtifactStatus, ArtifactType, Producer
from vdagent_orchestrator.llm1 import PROMPT_VERSION
from vdagent_orchestrator.records import RunRecord

AGENT_VERSION = "4.0.0"
log = logging.getLogger(__name__)


def _producer() -> Producer:
    return Producer(agent="orchestrator", agent_version=AGENT_VERSION, prompt_version=PROMPT_VERSION)


def run_state_draft(run: RunRecord) -> ArtifactDraft:
    steps = [{"step_id": s.step_id, "agent": s.agent, "operation": s.operation, "inputs": s.inputs,
              "waits": [w.model_dump(mode="json") for w in s.waits], "replaces": s.replaces} for s in run.plan.steps]
    payload = {"plan_id": run.plan.plan_id, "plan_version": run.plan.version, "plan_source": run.plan.source,
               "limited_mode": run.plan.limited_mode, "question": run.frame.original_question,
               "intent_frame": run.frame.model_dump(mode="json"), "catalog_versions": run.plan.catalog_versions,
               "steps": steps}
    return ArtifactDraft(artifact_type=ArtifactType.RUN_STATE, schema_version="run_state.v1", status=ArtifactStatus.VALID,
                         producer=_producer(), payload=payload)


def run_summary_draft(run: RunRecord) -> ArtifactDraft:
    assert run.summary is not None
    status = {"completed": ArtifactStatus.VALID, "partial": ArtifactStatus.PARTIAL}.get(run.status, ArtifactStatus.INVALID)
    missing = [p["error_code"] or p["status"] for p in run.summary["missing_parts"]]
    refs = [ref for s in run.ordered() if s.status == "completed" for ref in s.refs]
    return ArtifactDraft(
        artifact_type=ArtifactType.RUN_SUMMARY, schema_version="run_summary.v1", status=status, producer=_producer(),
        snapshot_refs=[run.snapshot_id] if run.snapshot_id else [], semantic_config_version=run.semantic_config_version,
        input_artifact_refs=refs, limitations=missing or ([run.summary["reason"]] if status is ArtifactStatus.PARTIAL else []),
        reason_code=None if status is ArtifactStatus.VALID else run.summary["reason"], payload=run.summary)


async def put(session: McpSession, draft: ArtifactDraft, run_id: str) -> str | None:
    """Best effort: a failed write is logged, never fails the run."""
    body = json.dumps(draft.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
    outcome = await session.call_tool("artifact_put", {"draft_json": body, "run_id": run_id})
    if outcome.is_error:
        log.warning("orchestrator artifact_put %s failed: %s", draft.artifact_type, outcome.text)
        return None
    return str(json.loads(outcome.text)["artifact_id"])


__all__ = ["put", "run_state_draft", "run_summary_draft"]
