from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import ArtifactRef, ChartTaskInput, Intent, Scope, VisualTarget
from .policy import load_policy


@dataclass(frozen=True)
class MockUpstreamBundle:
    task: ChartTaskInput
    artifacts: list[dict[str, Any]]
    llm_suggestions: dict[str, dict[str, Any]]
    summary: str


@dataclass(frozen=True)
class MockUpstreamEvent:
    agent: str
    status: str
    message: str
    details: dict[str, Any]

    def to_message(self) -> str:
        return f"{self.agent} {self.status}: {self.message}"


EventSink = Callable[[MockUpstreamEvent], Awaitable[None]]


class MockUpstreamReasoner(Protocol):
    async def decide_orchestration(self, question: str, allowed_chart_types: tuple[str, ...]) -> dict[str, Any]: ...
    async def generate_metric_artifact(self, plan: dict[str, Any]) -> dict[str, Any]: ...
    async def generate_insight_artifact(self, plan: dict[str, Any], metric_payload: dict[str, Any]) -> dict[str, Any]: ...
    async def generate_comparison_artifact(
        self,
        plan: dict[str, Any],
        metric_payload: dict[str, Any],
        insight_payload: dict[str, Any],
    ) -> dict[str, Any]: ...
    async def generate_presentation_plan(
        self,
        plan: dict[str, Any],
        metric_payload: dict[str, Any],
        insight_payload: dict[str, Any],
        comparison_payload: dict[str, Any],
    ) -> dict[str, Any]: ...


def _hash_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _artifact(
    *,
    artifact_id: str,
    artifact_type: str,
    run_id: str,
    scope: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    envelope = {
        "artifact_id": artifact_id,
        "version": 1,
        "artifact_type": artifact_type,
        "run_id": run_id,
        "status": "validated",
        "scope": scope,
        "payload": payload,
        "limitations": ["Demo-only synthetic upstream evidence generated for Chart Agent testing."],
    }
    envelope["content_hash"] = _hash_json({key: envelope[key] for key in envelope if key != "content_hash"})
    return envelope


def _task(
    *,
    question: str,
    suffix: str,
    run_id: str,
    scope: Scope,
    target: VisualTarget,
    artifacts: list[dict[str, Any]],
) -> ChartTaskInput:
    return ChartTaskInput(
        "chart-task/2.0",
        run_id,
        f"mock_chart_task_{suffix}",
        "direct_visualization",
        scope,
        (target,),
        tuple(ArtifactRef(item["artifact_id"], item["version"], item["content_hash"]) for item in artifacts),
        "chart-policy/demo-1.0",
        f"mock-upstream-v1:{suffix}",
        Intent(
            "direct_visualization",
            question,
            {"source": "mock_llm_upstream", "demo_only": True},
        ),
        requested_by="u_000000000001",
        trace_context={"trace_id": run_id},
    )


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _llm_bundle(
    question: str,
    plan: dict[str, Any],
    metric_payload: dict[str, Any],
    insight_payload: dict[str, Any],
    comparison_payload: dict[str, Any],
) -> MockUpstreamBundle:
    policy = load_policy("chart-policy/demo-1.0")
    normalized = question.strip()
    suffix = hashlib.sha256(
        json.dumps(
            {
                "question": normalized,
                "plan": plan,
                "metric": metric_payload,
                "insight": insight_payload,
                "comparison": comparison_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:12]
    run_id = f"run_llm_mock_{suffix}"
    visual_question = str(plan.get("visual_question") or "relationship")
    preferred_chart_type = plan.get("preferred_chart_type") or plan.get("chart_type")
    preferred = preferred_chart_type if preferred_chart_type in policy.allowed_chart_types else None
    grain = str(plan.get("data_grain") or metric_payload.get("grain") or "unit")
    scope_dict = {
        "project_ids": list(plan.get("project_ids") or ["VHOP"]),
        "area_ids": list(plan.get("area_ids") or []),
        "snapshot_id": str(plan.get("snapshot_id") or "2026-06-30"),
        "data_grain": grain,
        "filters": [],
    }
    records = _as_records(metric_payload.get("records"))
    if not records:
        records = [{"label": "Synthetic", "value": 1}]
    metric_payload = {
        "metric_id": str(metric_payload.get("metric_id") or f"llm_metric_{suffix}"),
        "grain": grain,
        "unit": metric_payload.get("unit") or plan.get("unit") or "value",
        "records": records,
        **{key: value for key, value in metric_payload.items() if key not in {"metric_id", "grain", "unit", "records"}},
    }
    metric_id = f"llm_metric_{suffix}"
    insight_id = f"llm_insight_{suffix}"
    comparison_id = f"llm_comparison_{suffix}"
    insight_payload = {
        "insight_id": str(insight_payload.get("insight_id") or f"llm_insight_{suffix}"),
        "claim": str(insight_payload.get("claim") or "Synthetic LLM upstream insight for Chart Agent testing."),
        "confidence": insight_payload.get("confidence", 0.5),
        "evidence_refs": [f"{metric_id}@1"],
        **{key: value for key, value in insight_payload.items() if key not in {"insight_id", "claim", "confidence", "evidence_refs"}},
    }
    display_records = _as_records(comparison_payload.get("display_records")) or records
    comparison_payload = {
        "comparison_id": str(comparison_payload.get("comparison_id") or f"llm_comparison_{suffix}"),
        "comparison_metric": str(comparison_payload.get("comparison_metric") or plan.get("comparison_metric") or "synthetic_comparison"),
        "display_records": display_records,
        **{key: value for key, value in comparison_payload.items() if key not in {"comparison_id", "comparison_metric", "display_records"}},
    }
    artifacts = [
        _artifact(
            artifact_id=metric_id,
            artifact_type="metric",
            run_id=run_id,
            scope=scope_dict,
            payload=metric_payload,
        ),
        _artifact(
            artifact_id=insight_id,
            artifact_type="insight",
            run_id=run_id,
            scope=scope_dict,
            payload=insight_payload,
        ),
        _artifact(
            artifact_id=comparison_id,
            artifact_type="comparison",
            run_id=run_id,
            scope=scope_dict,
            payload=comparison_payload,
        ),
    ]
    target = VisualTarget(
        f"vt_llm_{visual_question}",
        visual_question,
        preferred_chart_type=preferred,
        artifact_ids=tuple(item["artifact_id"] for item in artifacts),
    )
    task = _task(
        question=question,
        suffix=suffix,
        run_id=run_id,
        scope=Scope(tuple(scope_dict["project_ids"]), snapshot_id=scope_dict["snapshot_id"], data_grain=grain),
        target=target,
        artifacts=artifacts,
    )
    selection_chart_type = preferred or plan.get("selected_chart_type") or plan.get("chart_type")
    suggestions = {
        target.target_id: {
            "visual_question": {
                "type": visual_question,
                "reason": str(plan.get("visual_question_reason") or "LLM Orchestrator classified the visual question."),
            },
            "candidates": list(plan.get("candidates") or []),
            "selection": {
                "chart_type": selection_chart_type if selection_chart_type in policy.allowed_chart_types else None,
                "reason_codes": list(plan.get("reason_codes") or ["LLM_UPSTREAM_SELECTION"]),
            },
            "encoding": _as_dict(plan.get("encoding")),
            "presentation": _as_dict(plan.get("presentation")),
            "transform_intents": list(plan.get("transform_intents") or []),
        }
    }
    return MockUpstreamBundle(
        task,
        artifacts,
        suggestions,
        "LLM upstream generated Orchestrator, Data, Insight, and Compare artifacts.",
    )


def _relationship(question: str, suffix: str, run_id: str, scope_dict: dict[str, Any]) -> MockUpstreamBundle:
    metric_id = f"mock_metric_price_dom_{suffix}"
    insight_id = f"mock_insight_price_dom_{suffix}"
    comparison_id = f"mock_comparison_price_dom_{suffix}"
    artifacts = [
        _artifact(
            artifact_id=metric_id,
            artifact_type="metric",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "metric_id": "synthetic_price_dom_relationship",
                "grain": "unit",
                "unit": "million VND/m^2, days",
                "records": [
                    {"unit_id": "A12-08", "segment": "2BR 70-80m2", "price_m2": 68.0, "dom": 126},
                    {"unit_id": "A12-09", "segment": "2BR 70-80m2", "price_m2": 67.0, "dom": 110},
                    {"unit_id": "A13-03", "segment": "2BR 70-80m2", "price_m2": 69.0, "dom": 55},
                    {"unit_id": "A14-02", "segment": "2BR 80-90m2", "price_m2": 71.0, "dom": 70},
                    {"unit_id": "B08-11", "segment": "1BR 45-55m2", "price_m2": 72.0, "dom": 32},
                    {"unit_id": "B09-10", "segment": "1BR 45-55m2", "price_m2": 73.0, "dom": 43},
                    {"unit_id": "C01-01", "segment": "3BR 95-110m2", "price_m2": 74.0, "dom": 65},
                    {"unit_id": "C02-05", "segment": "3BR 95-110m2", "price_m2": 75.0, "dom": 88},
                ],
            },
        ),
        _artifact(
            artifact_id=insight_id,
            artifact_type="insight",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "insight_id": "synthetic_price_dom_pattern",
                "claim": "Higher price/m2 units show materially longer DOM in selected VHOP inventory.",
                "confidence": 0.72,
                "evidence_refs": [f"{metric_id}@1"],
                "narrative": "The mock Insight Agent flags a visible relationship to test scatter encoding, labels, and audit lineage.",
            },
        ),
        _artifact(
            artifact_id=comparison_id,
            artifact_type="comparison",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "comparison_id": "synthetic_price_dom_segments",
                "comparison_metric": "median_dom_by_price_band",
                "peer_definition": {
                    "project_id": "VHOP",
                    "property_type": "apartment",
                    "peer_count": 32,
                    "segmentation": "price_m2_band",
                },
                "display_records": [
                    {"label": "≤ 69m", "median_dom": 110},
                    {"label": "70-72m", "median_dom": 56},
                    {"label": "≥ 73m", "median_dom": 65},
                ],
            },
        ),
    ]
    target = VisualTarget(
        "vt_mock_relationship",
        "relationship",
        preferred_chart_type="scatter",
        artifact_ids=tuple(item["artifact_id"] for item in artifacts),
    )
    task = _task(
        question=question,
        suffix=suffix,
        run_id=run_id,
        scope=Scope(("VHOP",), snapshot_id=scope_dict["snapshot_id"], data_grain="unit"),
        target=target,
        artifacts=artifacts,
    )
    return MockUpstreamBundle(
        task,
        artifacts,
        {
            target.target_id: {
                "visual_question": {
                    "type": "relationship",
                    "reason": "The user asks how two continuous measures move together.",
                },
                "candidates": [
                    {"chart_type": "scatter", "reason": "Shows relationship between price/m2 and DOM per unit."},
                    {"chart_type": "heatmap", "reason": "Possible if upstream bins both measures."},
                ],
                "selection": {"chart_type": "scatter", "reason_codes": ["LLM_RELATIONSHIP_SCATTER"]},
                "encoding": {
                    "x": {"field": "price_m2", "type": "quantitative", "title": "$P_v(\\mathrm{million}\\ VND)/m^2$"},
                    "y": {"field": "dom", "type": "quantitative", "title": "DOM (days)"},
                    "detail": {"field": "unit_id", "type": "nominal"},
                    "color": {"field": "segment", "type": "nominal"},
                },
                "presentation": {
                    "title": "Giá/m² và DOM — VHOP",
                    "subtitle": "Mock Orchestrator/Data/Insight/Compare artifacts; Chart Agent validates and renders.",
                    "axes": {
                        "x": {"title": "$P_v(\\mathrm{million}\\ VND)/m^2$"},
                        "y": {"title": "DOM (days)"},
                    },
                    "annotations": ["Synthetic evidence for Chart Agent demo only."],
                },
            }
        },
        "Mock upstream generated Orchestrator, Data, Insight, and Compare artifacts for a relationship chart.",
    )


def _funnel(question: str, suffix: str, run_id: str, scope_dict: dict[str, Any]) -> MockUpstreamBundle:
    metric_id = f"mock_metric_funnel_{suffix}"
    insight_id = f"mock_insight_funnel_{suffix}"
    comparison_id = f"mock_comparison_funnel_{suffix}"
    artifacts = [
        _artifact(
            artifact_id=metric_id,
            artifact_type="metric",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "metric_id": "synthetic_sales_funnel",
                "grain": "stage",
                "unit": "count",
                "records": [
                    {"stage": "Visit", "order": 1, "count": 520},
                    {"stage": "Deposit", "order": 2, "count": 104},
                    {"stage": "Booking", "order": 3, "count": 78},
                    {"stage": "Contract", "order": 4, "count": 49},
                ],
            },
        ),
        _artifact(
            artifact_id=insight_id,
            artifact_type="insight",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "insight_id": "synthetic_funnel_dropoff",
                "claim": "The largest mock drop-off happens from Visit to Deposit.",
                "confidence": 0.81,
                "evidence_refs": [f"{metric_id}@1"],
            },
        ),
        _artifact(
            artifact_id=comparison_id,
            artifact_type="comparison",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "comparison_id": "synthetic_funnel_conversion",
                "comparison_metric": "stage_conversion_rate",
                "display_records": [
                    {"stage": "Visit→Deposit", "conversion_rate": 0.20},
                    {"stage": "Deposit→Booking", "conversion_rate": 0.75},
                    {"stage": "Booking→Contract", "conversion_rate": 0.63},
                ],
            },
        ),
    ]
    target = VisualTarget(
        "vt_mock_funnel",
        "funnel",
        preferred_chart_type="funnel",
        artifact_ids=tuple(item["artifact_id"] for item in artifacts),
    )
    task = _task(
        question=question,
        suffix=suffix,
        run_id=run_id,
        scope=Scope(("VHOP",), snapshot_id=scope_dict["snapshot_id"], data_grain="stage"),
        target=target,
        artifacts=artifacts,
    )
    return MockUpstreamBundle(
        task,
        artifacts,
        {
            target.target_id: {
                "visual_question": {"type": "funnel", "reason": "The user explicitly asks for a sales funnel."},
                "candidates": [
                    {"chart_type": "funnel", "reason": "Best fit for ordered conversion stages."},
                    {"chart_type": "bar", "reason": "Fallback if funnel renderer is unavailable."},
                ],
                "selection": {"chart_type": "funnel", "reason_codes": ["LLM_EXPLICIT_FUNNEL"]},
                "encoding": {
                    "x": {"field": "stage", "type": "ordinal"},
                    "y": {"field": "count", "type": "quantitative"},
                },
                "presentation": {
                    "title": "Phễu bán hàng — VHOP",
                    "subtitle": "Synthetic upstream pipeline for Chart Agent rendering test.",
                },
            }
        },
        "Mock upstream generated ordered funnel-stage evidence.",
    )


def _peer(question: str, suffix: str, run_id: str, scope_dict: dict[str, Any]) -> MockUpstreamBundle:
    metric_id = f"mock_metric_dom_target_{suffix}"
    insight_id = f"mock_insight_dom_gap_{suffix}"
    comparison_id = f"mock_comparison_dom_peer_{suffix}"
    artifacts = [
        _artifact(
            artifact_id=metric_id,
            artifact_type="metric",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "metric_id": "synthetic_target_dom",
                "grain": "unit",
                "unit": "days",
                "records": [
                    {"label": "A12-08", "dom": 126},
                ],
            },
        ),
        _artifact(
            artifact_id=insight_id,
            artifact_type="insight",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "insight_id": "synthetic_dom_peer_gap",
                "claim": "A12-08 is materially slower than comparable peers in the mock comparison set.",
                "confidence": 0.78,
                "evidence_refs": [f"{metric_id}@1", f"{comparison_id}@1"],
            },
        ),
        _artifact(
            artifact_id=comparison_id,
            artifact_type="comparison",
            run_id=run_id,
            scope=scope_dict,
            payload={
                "comparison_id": "synthetic_dom_peer",
                "grain": "unit",
                "unit": "days",
                "comparison_metric": "days_on_market",
                "target_value": 126,
                "peer_aggregate": 91,
                "gap": 35,
                "peer_definition": {
                    "project_id": "VHOP",
                    "property_type": "apartment",
                    "bedrooms": 2,
                    "area_range_m2": [70, 80],
                    "building_class": "similar",
                    "peer_count": 24,
                },
                "peer_population": {
                    "count": 24,
                    "selection_rule": "same project, same bedroom count, similar area, active comparable stock",
                },
                "peer_breakdown": [
                    {"label": "Peer - A01", "dom": 87},
                    {"label": "Peer - A02", "dom": 94},
                    {"label": "Peer - A03", "dom": 91},
                ],
                "display_records": [
                    {"label": "A12-08", "dom": 126},
                    {"label": "Peer - A01", "dom": 87},
                    {"label": "Peer - A02", "dom": 94},
                    {"label": "Peer - A03", "dom": 91},
                ],
            },
        ),
    ]
    target = VisualTarget(
        "vt_mock_dom_peer",
        "target_vs_peer",
        preferred_chart_type="bar",
        artifact_ids=tuple(item["artifact_id"] for item in artifacts),
    )
    task = _task(
        question=question,
        suffix=suffix,
        run_id=run_id,
        scope=Scope(("VHOP",), snapshot_id=scope_dict["snapshot_id"], data_grain="unit"),
        target=target,
        artifacts=artifacts,
    )
    return MockUpstreamBundle(
        task,
        artifacts,
        {
            target.target_id: {
                "visual_question": {
                    "type": "target_vs_peer",
                    "reason": "The user asks to compare one target unit with its peer group.",
                },
                "candidates": [
                    {"chart_type": "bar", "reason": "Compares target value against peer breakdown categories."},
                    {"chart_type": "bullet", "reason": "Useful if only target and one aggregate peer benchmark are shown."},
                ],
                "selection": {"chart_type": "bar", "reason_codes": ["LLM_TARGET_VS_PEER_BAR"]},
                "encoding": {
                    "x": {"field": "label", "type": "nominal"},
                    "y": {"field": "dom", "type": "quantitative"},
                    "sort": {"field": "dom", "order": "descending"},
                },
                "presentation": {
                    "title": "DOM mục tiêu so với peer — VHOP",
                    "subtitle": "Peer group: 24 căn 2BR, 70–80 m², cùng dự án VHOP.",
                    "axes": {
                        "x": {"title": "Nhóm so sánh"},
                        "y": {"title": "DOM (days)"},
                    },
                    "annotations": ["Peer definition and values are synthetic upstream artifacts."],
                },
            }
        },
        "Mock upstream generated target metric, insight narrative, and comparison peer-definition artifacts.",
    )


def build_mock_upstream(question: str) -> MockUpstreamBundle:
    normalized = question.strip()
    digest = hashlib.sha256(normalized.lower().encode()).hexdigest()[:12]
    run_id = f"run_mock_{digest}"
    lower = normalized.lower()
    scope = {
        "project_ids": ["VHOP"],
        "area_ids": [],
        "snapshot_id": "2026-06-30",
        "data_grain": "stage" if any(token in lower for token in ("funnel", "phễu", "pheu")) else "unit",
        "filters": [],
    }
    if any(token in lower for token in ("funnel", "phễu", "pheu")):
        return _funnel(normalized, digest, run_id, scope)
    if any(token in lower for token in ("peer", "benchmark", "nhóm tương đồng", "nhom tuong dong")) and "dom" in lower:
        return _peer(normalized, digest, run_id, scope)
    return _relationship(normalized, digest, run_id, scope)


async def run_mock_upstream_pipeline(
    question: str,
    emit: EventSink | None = None,
    reasoner: MockUpstreamReasoner | None = None,
) -> MockUpstreamBundle:
    """Run demo-only LLM-like upstream agents before the real Chart Agent.

    The upstream steps are real async code paths so the UI can show which
    upstream agent is running and what each one produced. The evidence remains
    synthetic and is intended only for Chart Agent testing.
    """

    async def record(agent: str, status: str, message: str, details: dict[str, Any]) -> None:
        if emit is not None:
            await emit(MockUpstreamEvent(agent, status, message, details))

    await record(
        "Orchestrator",
        "running",
        "reading the user question and planning required upstream agents",
        {"question": question, "llm_model": "gpt-4o-mini"},
    )
    if reasoner is not None and hasattr(reasoner, "decide_orchestration"):
        try:
            policy = load_policy("chart-policy/demo-1.0")
            plan = await reasoner.decide_orchestration(question, policy.allowed_chart_types)
            if not isinstance(plan, dict):
                raise TypeError("LLM Orchestrator must return a JSON object")
            await record(
                "Orchestrator",
                "output",
                f"visual_question={plan.get('visual_question')}; chart_candidate={plan.get('preferred_chart_type') or plan.get('chart_type')}; next=Data Agent, Insight Agent, Compare Agent",
                {"plan": plan},
            )

            await record(
                "Data Agent",
                "running",
                "asking LLM Data Agent to synthesize a metric artifact",
                {"visual_question": plan.get("visual_question")},
            )
            metric_payload = await reasoner.generate_metric_artifact(plan)
            if not isinstance(metric_payload, dict):
                raise TypeError("LLM Data Agent must return a JSON object")
            await record(
                "Data Agent",
                "output",
                f"metric_id={metric_payload.get('metric_id')} rows={len(_as_records(metric_payload.get('records')))} grain={metric_payload.get('grain')}",
                {"payload": metric_payload},
            )

            await record(
                "Insight Agent",
                "running",
                "asking LLM Insight Agent to synthesize an insight artifact",
                {"metric_id": metric_payload.get("metric_id")},
            )
            insight_payload = await reasoner.generate_insight_artifact(plan, metric_payload)
            if not isinstance(insight_payload, dict):
                raise TypeError("LLM Insight Agent must return a JSON object")
            await record(
                "Insight Agent",
                "output",
                str(insight_payload.get("claim", "synthetic insight generated")),
                {"payload": insight_payload},
            )

            await record(
                "Compare Agent",
                "running",
                "asking LLM Compare Agent to synthesize comparison evidence",
                {"metric_id": metric_payload.get("metric_id")},
            )
            comparison_payload = await reasoner.generate_comparison_artifact(plan, metric_payload, insight_payload)
            if not isinstance(comparison_payload, dict):
                raise TypeError("LLM Compare Agent must return a JSON object")
            await record(
                "Compare Agent",
                "output",
                f"comparison_id={comparison_payload.get('comparison_id')} display_records={len(_as_records(comparison_payload.get('display_records')))}",
                {"payload": comparison_payload},
            )
            await record(
                "Presentation Agent",
                "running",
                "asking LLM to write business-readable chart title and subtitle",
                {"visual_question": plan.get("visual_question")},
            )
            presentation_plan = await reasoner.generate_presentation_plan(
                plan,
                metric_payload,
                insight_payload,
                comparison_payload,
            )
            if not isinstance(presentation_plan, dict):
                raise TypeError("LLM Presentation Agent must return a JSON object")
            plan = {**plan, "presentation": presentation_plan}
            await record(
                "Presentation Agent",
                "output",
                str(presentation_plan.get("title") or "LLM presentation generated"),
                {"payload": presentation_plan},
            )
            return _llm_bundle(question, plan, metric_payload, insight_payload, comparison_payload)
        except Exception as exc:
            await record(
                "Orchestrator",
                "output",
                f"LLM upstream unavailable or invalid; falling back to deterministic demo fixtures: {type(exc).__name__}",
                {"fallback": True},
            )
    bundle = build_mock_upstream(question)
    target = bundle.task.visual_targets[0]
    suggestion = bundle.llm_suggestions[target.target_id]
    await record(
        "Orchestrator",
        "output",
        f"visual_question={target.visual_question}; chart_candidate={suggestion['selection']['chart_type']}; next=Data Agent, Insight Agent, Compare Agent",
        {
            "task_id": bundle.task.task_id,
            "target_id": target.target_id,
            "artifact_ids": list(target.artifact_ids),
        },
    )

    metric = next(artifact for artifact in bundle.artifacts if artifact["artifact_type"] == "metric")
    records = list(metric["payload"].get("records", ()))
    await record(
        "Data Agent",
        "running",
        "materializing a synthetic metric artifact for Chart Agent validation",
        {"artifact_id": metric["artifact_id"]},
    )
    await record(
        "Data Agent",
        "output",
        f"{metric['artifact_id']}@1 rows={len(records)} grain={metric['payload'].get('grain')}",
        {
            "artifact_id": metric["artifact_id"],
            "content_hash": metric["content_hash"],
            "schema": sorted({field for row in records for field in row}),
        },
    )

    insight = next(artifact for artifact in bundle.artifacts if artifact["artifact_type"] == "insight")
    await record(
        "Insight Agent",
        "running",
        "turning the metric artifact into a synthetic insight narrative",
        {"artifact_id": insight["artifact_id"]},
    )
    await record(
        "Insight Agent",
        "output",
        str(insight["payload"].get("claim", "synthetic insight generated")),
        {
            "artifact_id": insight["artifact_id"],
            "confidence": insight["payload"].get("confidence"),
            "evidence_refs": insight["payload"].get("evidence_refs", []),
        },
    )

    comparison = next(artifact for artifact in bundle.artifacts if artifact["artifact_type"] == "comparison")
    display_records = list(comparison["payload"].get("display_records", ()))
    await record(
        "Compare Agent",
        "running",
        "building a synthetic comparison/evidence artifact for chart context",
        {"artifact_id": comparison["artifact_id"]},
    )
    await record(
        "Compare Agent",
        "output",
        f"{comparison['artifact_id']}@1 display_records={len(display_records)} metric={comparison['payload'].get('comparison_metric')}",
        {
            "artifact_id": comparison["artifact_id"],
            "content_hash": comparison["content_hash"],
            "peer_definition": comparison["payload"].get("peer_definition"),
            "display_records": display_records,
        },
    )
    return bundle
