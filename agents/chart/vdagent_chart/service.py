from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace

from .chart_plan import (
    chart_suggestion_from_plan,
    effective_visual_target,
    validate_encoding_plan,
    validate_presentation_plan,
)
from .contracts import ChartTaskInput, ChartTaskResult, ResolvedChartContext, TargetResult
from .dataset import assemble_dataset
from .errors import ChartError
from .evidence import build_evidence_map
from .fixture_store import FixtureArtifactStore
from .llm import VisualReasoner
from .output_validation import validate_chart_spec
from .policy import load_policy
from .profile import profile_target
from .rendering.plotly import render_plotly
from .schema import normalize_artifact
from .selection import select_chart
from .spec_builder import build_semantic_spec
from .telemetry import TelemetryPort
from .validation import validate_input
from .vega import render_vega


def _reasoning_for(llm_suggestions: Mapping[str, object] | None, target_id: str) -> dict[str, object]:
    value = (llm_suggestions or {}).get(target_id)
    return value if isinstance(value, dict) else {}


class ChartAgentService:
    """Deterministic execution entry point for fixture-backed Chart Agent demos."""

    def __init__(
        self,
        store: FixtureArtifactStore,
        *,
        reasoner: VisualReasoner | None = None,
        telemetry: TelemetryPort | None = None,
    ) -> None:
        self._store = store
        self._reasoner = reasoner
        self._telemetry = telemetry
        self.artifacts: dict[str, dict] = {}

    def execute(
        self, task: ChartTaskInput, llm_suggestions: Mapping[str, object] | None = None
    ) -> ChartTaskResult:
        try:
            resolved = [self._store.get_exact(ref) for ref in task.artifact_refs]
        except ChartError as exc:
            missing = next((ref for ref in task.artifact_refs if ref.artifact_id in str(exc)), task.artifact_refs[0])
            return ChartTaskResult(
                "chart-result/2.0",
                task.run_id,
                task.task_id,
                "failed",
                dependency_requests=({"artifact_id": missing.artifact_id, "version": missing.version, "code": exc.code},),
            )
        policy = load_policy(task.policy_ref)
        validate_input(task, resolved, policy)
        context = ResolvedChartContext(
            task,
            policy,
            tuple(normalize_artifact(artifact) for artifact in resolved),
            {"overall_result": "pass"},
        )
        refs: list[str] = []
        targets: list[TargetResult] = []
        errors: list[dict[str, str]] = []
        for target in task.visual_targets:
            try:
                reasoning = _reasoning_for(llm_suggestions, target.target_id)
                effective_target = effective_visual_target(target, reasoning)
                target_context = replace(context, task=replace(task, visual_targets=(effective_target,)))
                binding = build_evidence_map(target_context)[effective_target.target_id]
                suggestion = chart_suggestion_from_plan(reasoning, policy.allowed_chart_types)
                decision = select_chart(
                    effective_target,
                    policy,
                    suggestion,
                    profile_target(target_context, binding),
                )
                dataset = assemble_dataset(target_context, binding, decision)
            except ChartError as exc:
                targets.append(TargetResult(target.target_id, "failed", reason_code=exc.code))
                errors.append({"target_id": target.target_id, "code": exc.code, "message": exc.message})
                continue
            title = effective_target.visual_question.replace("_", " ").capitalize()
            presentation = validate_presentation_plan(reasoning, title, f"Snapshot {task.scope.snapshot_id or 'n/a'}")
            chart_id = f"chart_{task.task_id}_{effective_target.target_id}"
            lineage = [f"{artifact['artifact_id']}@{artifact['version']}" for artifact in resolved]
            semantic_spec = build_semantic_spec(
                chart_id=chart_id,
                task_id=task.task_id,
                target_id=effective_target.target_id,
                chart_type=str(decision["chart_type"]),
                purpose=task.intent.purpose,
                visual_question=effective_target.visual_question,
                scope={"snapshot_id": task.scope.snapshot_id, "data_grain": task.scope.data_grain},
                dataset=dataset,
                selection=decision,
                presentation=presentation,
                lineage={"input_artifact_refs": lineage},
                validation={"overall_result": "pass"},
            )
            encoding = validate_encoding_plan(reasoning, dataset)
            if encoding:
                semantic_spec["encoding"] = {**semantic_spec["encoding"], **encoding}
            output = validate_chart_spec(semantic_spec)
            if output["overall_result"] != "pass":
                raise ChartError("OUT-001", "semantic chart spec failed output validation", "output")
            semantic_spec["validation"] = output
            semantic_spec["vega_render_spec"] = render_vega(semantic_spec)
            render_spec = render_plotly(semantic_spec)
            semantic_spec["render_spec"] = render_spec
            content = {
                "chart_type": decision["chart_type"],
                "dataset": dataset,
                "render_spec": render_spec,
                "semantic_spec": semantic_spec,
                "lineage": lineage,
            }
            content_hash = "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
            self.artifacts[chart_id] = {
                "artifact_id": chart_id,
                "version": 1,
                "status": "validated",
                **content,
                "content_hash": content_hash,
                "selection": decision,
                "presentation": presentation,
            }
            refs.append(f"{chart_id}@1")
            targets.append(TargetResult(effective_target.target_id, "success", f"{chart_id}@1"))
        status = "success" if not errors else "partial" if refs else "failed"
        return ChartTaskResult(
            "chart-result/2.0",
            task.run_id,
            task.task_id,
            status,
            tuple(refs),
            tuple(targets),
            errors=tuple(errors),
        )

    async def execute_async(self, task: ChartTaskInput) -> ChartTaskResult:
        """Run optional bounded LLM visual reasoning, then the deterministic workflow."""
        event_context = {
            "trace_id": task.trace_context.get("trace_id", task.run_id),
            "task_id": task.task_id,
            "policy_version": task.policy_ref,
            "validator_version": "chart-spec/2.0",
            "renderer_version": "plotly.js",
        }
        self._record("chart.started", {**event_context, "target_count": len(task.visual_targets)})
        suggestions: dict[str, object] = {}
        if self._reasoner is not None:
            policy = load_policy(task.policy_ref)
            try:
                resolved = [self._store.get_exact(ref) for ref in task.artifact_refs]
            except ChartError:
                resolved = []
            for target in task.visual_targets:
                try:
                    payload = {
                        "visual_target": {
                            "target_id": target.target_id,
                            "purpose": target.purpose,
                            "visual_question": target.visual_question,
                            "preferred_chart_type": target.preferred_chart_type,
                        },
                        "intent": {
                            "purpose": task.intent.purpose,
                            "business_question": task.intent.business_question,
                            "presentation_context": task.intent.presentation_context,
                        },
                        "scope": {
                            "project_ids": task.scope.project_ids,
                            "snapshot_id": task.scope.snapshot_id,
                            "data_grain": task.scope.data_grain,
                        },
                        "artifacts": [
                            {
                                "artifact_id": artifact["artifact_id"],
                                "artifact_type": artifact["artifact_type"],
                                "scope": artifact.get("scope", {}),
                                "payload": artifact.get("payload", {}),
                            }
                            for artifact in resolved
                            if not target.artifact_ids or artifact["artifact_id"] in target.artifact_ids
                        ],
                    }
                    if hasattr(self._reasoner, "decide"):
                        suggestions[target.target_id] = await self._reasoner.decide(payload, policy.allowed_chart_types)
                    else:
                        suggestions[target.target_id] = {
                            "selected_chart_type": await self._reasoner.suggest(
                                target.visual_question, policy.allowed_chart_types
                            )
                        }
                except Exception:
                    suggestions[target.target_id] = None
                    self._record("chart.llm.unavailable", {**event_context, "target_count": 1})
        result = self.execute(task, suggestions)
        self._record(
            "chart.completed",
            {**event_context, "status": result.status, "artifact_count": len(result.chart_artifacts)},
        )
        return result

    def _record(self, name: str, attributes: Mapping[str, str | int | bool]) -> None:
        if self._telemetry is not None:
            self._telemetry.record(name, attributes)
