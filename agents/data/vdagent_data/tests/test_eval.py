"""E1–E8 on the golden set (build spec 02 §10) — the merge gate: E6 > 0 or an E2 drop blocks."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from vdagent_backend.re_warehouse import build
from vdagent_data.eval import graders
from vdagent_data.eval.runner import TaskRun, load_tasks, run_all, run_task


@pytest.fixture(scope="module")
def runs(dw_path: str) -> list[TaskRun]:
    return asyncio.run(run_all(dw_path))  # sync + asyncio.run: pytest-asyncio loops are per function


def assert_passed(*scores: graders.Score) -> None:
    for score in scores:
        assert score.passed, f"{score.name} = {score.value} < {score.threshold}: {score.detail}"


def test_golden_set_has_20_tasks_in_5_groups() -> None:
    tasks = load_tasks()
    assert len(tasks) == 20 and {t.group for t in tasks} == {"kpi", "slow", "peer", "ambiguous", "attack"}


def test_data_e1_entity_tier_schema_recall(runs: list[TaskRun]) -> None:
    assert_passed(*graders.e1_understanding(runs))


def test_data_e2_execution_accuracy(runs: list[TaskRun], dw_path: str) -> None:
    assert_passed(graders.e2_execution(runs, dw_path))


async def test_data_e2b_five_shuffled_variants(runs: list[TaskRun], dw_path: str, tmp_path: Path) -> None:
    tasks = [r.task for r in runs if r.task.reference_sql]
    base, _ = graders.execution_accuracy(runs, dw_path)
    scores = []
    for seed in (1, 2, 3, 4, 5):
        path = str(tmp_path / f"v{seed}.db")
        build(path, seed=seed)
        scores.append(graders.execution_accuracy(await run_all(path, tasks), path)[0])
    assert_passed(graders.e2b_variants(base, scores))
    assert scores == [Decimal(1)] * 5


def test_data_e3_manifest_valid(runs: list[TaskRun]) -> None:
    assert_passed(graders.e3_package(runs))


async def test_data_e4_pass5_and_paraphrase(runs: list[TaskRun], dw_path: str) -> None:
    stable = [r.task for r in runs if r.task.expect["state"] == "completed"][:6]
    repeats = [[await run_task(t, dw_path) for _ in range(5)] for t in stable]
    paraphrased = [(r, await run_task(r.task, dw_path, mention_override=p)) for r in runs for p in r.task.paraphrases]
    assert len(paraphrased) == 3
    assert_passed(*graders.e4_stability(repeats, paraphrased))


def test_data_e5_question_precision_recall(runs: list[TaskRun]) -> None:
    assert_passed(*graders.e5_questions(runs))


def test_data_e6_zero_violations(runs: list[TaskRun]) -> None:
    assert_passed(graders.e6_safety(runs))
    assert sum(len(r.executed_sql) for r in runs) > 20


def test_data_e7_planted_dq_recall() -> None:
    assert_passed(graders.e7_dq())


def test_data_e8_latency_recorded_not_gated(runs: list[TaskRun]) -> None:
    score = graders.e8_operations(runs)
    assert score.threshold is None and score.passed and "p50" in score.detail
