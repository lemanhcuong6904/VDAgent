"""Narrow GPT-4o-mini adapter; its suggestions never bypass deterministic policy."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from .settings import Settings


class VisualReasoner(Protocol):
    async def decide(self, payload: dict[str, Any], allowed_chart_types: tuple[str, ...]) -> dict[str, Any] | None: ...
    async def suggest(self, visual_question: str, allowed_chart_types: tuple[str, ...]) -> str | None: ...


class OpenAIVisualReasoner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _complete_json(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        import litellm

        async with asyncio.timeout(self._settings.llm_timeout_s):
            response = await litellm.acompletion(
                model=f"openai/{self._settings.llm_model}", api_base=self._settings.openai_base_url,
                api_key=self._settings.openai_api_key, temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
        try:
            value = json.loads(response.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        return value

    async def decide(self, payload: dict[str, Any], allowed_chart_types: tuple[str, ...]) -> dict[str, Any] | None:
        prompt = {**payload, "allowed_chart_types": allowed_chart_types}
        value = await self._complete_json(
            (
                "Return only JSON for a ChartPlan. Use keys: visual_target, visual_question, "
                "candidates, selection, encoding, presentation, transform_intents. "
                "visual_question must be an object with type and reason. candidates must be chart_type/reason pairs. "
                "selection.chart_type must be one allowed value or null. "
                "Encoding fields must come from the provided artifacts only. "
                "Presentation must include a business-readable title and subtitle, plus axes.x.title and axes.y.title "
                "when the chart has axes. Axis title objects should use {format:'plain', value:'...'} or "
                "{format:'math', value:'$...$'} for metrics such as price per square meter, DOM, deltas, or ratios. "
                "Prefer concise Vietnamese labels and LaTeX/MathJax syntax for units and formulas where helpful. "
                "Never wrap a full Vietnamese prose label in '$...$'; use plain format for prose and math format only for formulas. "
                "Do not invent fields, do not change data values, do not generate Plotly code."
            ),
            prompt,
        )
        if value is None:
            return None
        selection = value.get("selection")
        selected = (
            selection.get("chart_type")
            if isinstance(selection, dict)
            else value.get("selected_chart_type") or value.get("chart_type")
        )
        if selected not in allowed_chart_types:
            value["selected_chart_type"] = None
        else:
            value["selected_chart_type"] = selected
        return value

    async def suggest(self, visual_question: str, allowed_chart_types: tuple[str, ...]) -> str | None:
        decision = await self.decide({"visual_question": visual_question}, allowed_chart_types)
        selected = None if decision is None else decision.get("selected_chart_type")
        return selected if isinstance(selected, str) and selected in allowed_chart_types else None

    async def decide_orchestration(self, question: str, allowed_chart_types: tuple[str, ...]) -> dict[str, Any]:
        value = await self._complete_json(
            (
                "You are the mock LLM Orchestrator for a Chart Agent demo. Return only JSON. "
                "Classify the user's question into a visual_question and preferred_chart_type. "
                "Use visual_question values such as current_value, trend, comparison, target_vs_peer, "
                "composition, distribution, distribution_comparison, relationship, matrix, geospatial, "
                "funnel, additive_change, hierarchy, actual_vs_target. "
                "Use preferred_chart_type only from allowed_chart_types. Include data_grain, presentation, "
                "encoding, candidates, and concise reason_codes when helpful. Do not create chart specs or Plotly code."
            ),
            {"question": question, "allowed_chart_types": allowed_chart_types},
        )
        return value or {}

    async def generate_metric_artifact(self, plan: dict[str, Any]) -> dict[str, Any]:
        value = await self._complete_json(
            (
                "You are the mock LLM Data Agent for a Chart Agent demo. Return only JSON for a metric payload. "
                "The payload must include metric_id, grain, unit, and records. "
                "records must be a non-empty list of small synthetic but plausible objects. "
                "Use only JSON values. Do not include artifact envelope fields, SQL, markdown, or code."
            ),
            {"orchestration_plan": plan},
        )
        return value or {}

    async def generate_insight_artifact(self, plan: dict[str, Any], metric_payload: dict[str, Any]) -> dict[str, Any]:
        value = await self._complete_json(
            (
                "You are the mock LLM Insight Agent for a Chart Agent demo. Return only JSON for an insight payload. "
                "Include insight_id, claim, confidence, and optional narrative. Base the claim only on the provided synthetic metric payload. "
                "Do not include artifact envelope fields, markdown, or code."
            ),
            {"orchestration_plan": plan, "metric_payload": metric_payload},
        )
        return value or {}

    async def generate_comparison_artifact(
        self,
        plan: dict[str, Any],
        metric_payload: dict[str, Any],
        insight_payload: dict[str, Any],
    ) -> dict[str, Any]:
        value = await self._complete_json(
            (
                "You are the mock LLM Compare Agent for a Chart Agent demo. Return only JSON for a comparison payload. "
                "Include comparison_id, comparison_metric, and display_records. "
                "For target_vs_peer, include peer_definition, peer_population, target_value, peer_aggregate, gap, and display_records. "
                "The values may be synthetic but must be plausible and consistent enough for chart testing. "
                "Do not include artifact envelope fields, markdown, or code."
            ),
            {
                "orchestration_plan": plan,
                "metric_payload": metric_payload,
                "insight_payload": insight_payload,
            },
        )
        return value or {}

    async def generate_presentation_plan(
        self,
        plan: dict[str, Any],
        metric_payload: dict[str, Any],
        insight_payload: dict[str, Any],
        comparison_payload: dict[str, Any],
    ) -> dict[str, Any]:
        value = await self._complete_json(
            (
                "You are the mock LLM Presentation Agent for a Chart Agent demo. Return only JSON. "
                "Write a business-readable chart presentation with title and subtitle. "
                "The title must describe what the chart means, not just the chart type. "
                "Avoid generic titles such as 'Composition — VHop', 'Relationship — VHop', or 'Chart'. "
                "Use the user's intent, visual question, fields, sample records, insight, and comparison context. "
                "Do not include causal claims unless explicitly supported by the insight payload. "
                "Do not include PII, HTML, markdown, Plotly code, or prompt text. "
                "Return keys: title, subtitle, optional annotations, optional axes."
            ),
            {
                "orchestration_plan": plan,
                "metric_payload": metric_payload,
                "insight_payload": insight_payload,
                "comparison_payload": comparison_payload,
            },
        )
        return value or {}
