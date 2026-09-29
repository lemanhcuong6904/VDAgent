"""Eval runner (build spec 02 §10.3): runs golden tasks through the real pipeline on a DW mock.

Dev tooling, like the tests: it imports the Backend's scoped SQL and DW builder (DEC-041); the plugin runtime never
does. No LLM: T1/T2 tasks are graded deterministically; real-LLM runs are opt-in and out of CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport
from vdagent_data.pipeline.machine import run_step
from vdagent_data.tests.fakes import DwMcp

GOLDEN = Path(__file__).resolve().parent / "golden.yaml"
USER = "u_000000000001"


@dataclass(frozen=True)
class Task:
    id: str
    group: str
    question: str
    operation: str
    spec: dict[str, Any]
    expect: dict[str, Any]
    metric: str | None = None
    reference_sql: str | None = None
    paraphrases: list[str] = field(default_factory=list)


@dataclass
class TaskRun:
    task: Task
    report: AgentReport
    payload: dict[str, Any] | None
    executed_sql: list[str]


def load_tasks(path: Path = GOLDEN) -> list[Task]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["tasks"]
    return [Task(**{k: v for k, v in t.items()}) for t in raw]


def _step_spec(task: Task, mention_override: str | None = None) -> StepSpec:
    spec = dict(task.spec)
    mentions = spec.pop("mentions", [])
    scope_all = spec.pop("scope_all", False)
    question = task.question
    if mention_override is not None and mentions:
        question = question.replace(mentions[0][0], mention_override)
        mentions = [[mention_override, mentions[0][1]], *mentions[1:]]
    body: dict[str, Any] = {"objective": question[:300],
                            "scope": {"mentions": [{"text": t, "kind_hint": k} for t, k in mentions], "scope_all": scope_all},
                            **spec}
    if "target_unit" in body:
        text, kind = body["target_unit"]
        body["target_unit"] = {"text": text, "kind_hint": kind}
    return StepSpec(run_id="t_eval", plan_id=f"EVAL-{task.id}", step_id="B1", idempotency_key=f"EVAL-{task.id}:B1",
                    operation=task.operation, spec=body, original_question=question,
                    user_context={"user_id": USER, "authorized_scope": {"project_ids": ["PRJ-X"]}})


async def run_task(task: Task, dw_path: str, *, mention_override: str | None = None) -> TaskRun:
    mcp = DwMcp(dw_path, task_id="t_eval")
    report = await run_step(_step_spec(task, mention_override), mcp, None, user_id=USER)
    payload = None
    if report.artifact_refs:
        payload = mcp.artifacts[report.artifact_refs[0].artifact_id][-1]["payload"]
    return TaskRun(task, report, payload, [c["sql"] for c in mcp.called("re_run_query")])


async def run_all(dw_path: str, tasks: list[Task] | None = None) -> list[TaskRun]:
    return [await run_task(t, dw_path) for t in (tasks or load_tasks())]
