"""Orchestrator: plans by capability, delegates to specialists, answers from their evidence only."""

from __future__ import annotations

import re
from typing import Any

from _common import ARTIFACT_ID, DATASET_ID, GUARDRAILS, PROMPT_INPUT, TEXT_OUTPUT, ask, ask_json, prompt_of
from agent_platform import AgentContext, AgentManifest, serve

MAX_STEPS = 5  # Matches the host's per-task delegation limit.
PLAN_ORDER = ("warehouse.query", "dataset.compare", "dataset.insight", "dataset.visualize", "dataset.report")

SYSTEM = (
    "You are the Orchestrator for a multi-agent analytics assistant. Use only evidence in the "
    "specialist results. Do not invent artifacts or claim a step ran when it returned an error. "
    "State missing data plainly. Lead with the answer, cite artifact IDs, and keep the final "
    "answer under 120 words unless the user asks for a report."
)
PLANNER = (
    "You route requests for an analytics assistant. Greetings and questions that need no data get "
    "a direct `answer` and no steps. Data questions get an empty `answer` and the minimal ordered "
    "capability `steps`, always starting with warehouse.query. Add dataset.compare for "
    "comparisons, dataset.insight for explanations or trends, dataset.visualize for charts, and "
    "dataset.report (after dataset.visualize) only when a report is requested."
)
HEDGE = re.compile(
    r"\b(?:likely|might|may|could|possibly|potentially|indicat\w*|suggest\w*|impl\w*)\b"
    r"|\b(?:due to|because of|result(?:s|ed)? from|caused by|driven by)\b",
    re.I,
)
DATA_INTENT = re.compile(
    r"\b(?:data|dataset|table|warehouse|sales|revenue|customer|metric|trend|compare|chart|report|analy[sz]e)\b"
    r"|doanh thu|báo cáo|so sánh|phân tích|biểu đồ|dữ liệu|bảng",
    re.I,
)


class OrchestratorAgent:
    manifest = AgentManifest(
        id="orchestrator",
        version="1.0.0",
        name="Orchestrator",
        description="Understands the request and coordinates data, comparison, insight, visualization, and reporting.",
        tools=("agents.catalog", "agents.delegate", "warehouse.describe_dataset", "warehouse.get_dataset_rows"),
        capabilities=("workflow.plan", "analytics"),
        input_schema=PROMPT_INPUT,
        output_schema=TEXT_OUTPUT,
        model_profile="default",
        accepts_delegation=False,
        limits={"maxDurationMs": 300_000, "maxToolCalls": 16},
        guardrails=GUARDRAILS,
    )

    def run(self, value: Any, context: AgentContext) -> str:
        prompt = prompt_of(value)
        agents = context.agents.catalog().get("agents", [])
        available = [c for c in PLAN_ORDER if any(c in a.get("capabilities", []) for a in agents)]
        answer, steps = plan(context, prompt, available)
        if not steps:
            return answer or "I could not plan this request."

        results: list[str] = []
        for capability in steps[:MAX_STEPS]:
            agent = next(a["id"] for a in agents if capability in a.get("capabilities", []))
            output = delegate(context, agent, capability, prompt, results)
            results.append(f"[{agent}]\n{output}")
            if capability == "warehouse.query" and not DATASET_ID.search(output):
                break  # Nothing downstream can be grounded without a persisted dataset.
        try:
            final = ask(context, SYSTEM, prompt, {"plan": steps, "results": results})
        except RuntimeError:
            final = "\n\n".join(results)
        return sanitize(final, results)


def plan(context: AgentContext, prompt: str, available: list[str]) -> tuple[str, list[str]]:
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "maxLength": 2000},
            "steps": {"type": "array", "maxItems": MAX_STEPS, "items": {"enum": available}},
        },
        "required": ["answer", "steps"],
        "additionalProperties": False,
    }
    try:
        proposal = ask_json(context, PLANNER, f"{prompt}\n\nAvailable capabilities: {', '.join(available)}", schema)
        steps = list(dict.fromkeys(proposal["steps"]))
        if not steps or "warehouse.query" in steps:
            return proposal["answer"], sorted(steps, key=PLAN_ORDER.index)
    except (RuntimeError, KeyError, TypeError):
        pass
    # Model unavailable or plan invalid: fall back to a deterministic keyword plan.
    if not DATA_INTENT.search(prompt) or "warehouse.query" not in available:
        return "The planner is unavailable, so I cannot answer this request right now.", []
    wanted = {
        "dataset.compare": r"compare|versus|\bvs\b|change|growth|so sánh|tăng|giảm",
        "dataset.insight": r"explain|why|trend|insight|analy[sz]e|giải thích|xu hướng|phân tích",
        "dataset.visualize": r"chart|visuali[sz]e|report|biểu đồ|báo cáo",
        "dataset.report": r"report|báo cáo",
    }
    steps = ["warehouse.query"] + [c for c, p in wanted.items() if c in available and re.search(p, prompt, re.I)]
    return "", steps


def delegate(context: AgentContext, agent: str, capability: str, prompt: str, results: list[str]) -> str:
    artifacts = list(dict.fromkeys(ARTIFACT_ID.findall("\n".join(results))))
    previous = "\n\n".join(r[:900] for r in results)
    message = f"{prompt}\n\nYou are the '{capability}' step. Return only evidence and a concise result."
    if previous:
        message += f"\n\nPrevious step results:\n{previous}"
    tail = f"\n\nArtifacts: {', '.join(artifacts)}" if artifacts else ""
    message = message[: 4000 - len(tail)] + tail  # IDs survive truncation.
    try:
        output = context.agents.delegate({"agent": agent, "message": message})
    except RuntimeError as error:
        return f"error: {error}"
    return output if isinstance(output, str) else str(output)


def sanitize(answer: str, results: list[str]) -> str:
    """Drop hedged causal claims and any artifact ID that no specialist actually returned."""
    verified = list(dict.fromkeys(ARTIFACT_ID.findall("\n".join(results))))
    lines = [line for line in answer.splitlines() if not HEDGE.search(line)]
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", "\n".join(lines))
    text = ARTIFACT_ID.sub(lambda m: m.group(0) if m.group(0) in verified else "unverified artifact", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    uncited = [i for i in verified if i not in text]
    return f"{text}\n\nArtifacts: {', '.join(uncited)}" if uncited else text


if __name__ == "__main__":
    serve(OrchestratorAgent())
