"""`uv run python -m vdagent_data.eval [DW_PATH]`: grade the golden set E1–E8 on the DW mock (+5 variants)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from vdagent_backend.re_warehouse import build
from vdagent_data.eval import graders
from vdagent_data.eval.runner import load_tasks, run_all, run_task

VARIANT_SEEDS = (1, 2, 3, 4, 5)


async def evaluate(dw_path: str, workdir: str) -> list[graders.Score]:
    tasks = load_tasks()
    runs = await run_all(dw_path, tasks)
    base, _misses = graders.execution_accuracy(runs, dw_path)
    variant_scores = []
    for seed in VARIANT_SEEDS:
        path = str(Path(workdir) / f"variant_{seed}.db")
        build(path, seed=seed)
        variant_scores.append(graders.execution_accuracy(await run_all(path, tasks), path)[0])
    stable_tasks = [t for t in tasks if t.expect["state"] == "completed"]
    repeats = [[await run_task(t, dw_path) for _ in range(5)] for t in stable_tasks]
    paraphrased = [(r, await run_task(r.task, dw_path, mention_override=p)) for r in runs for p in r.task.paraphrases]
    return [
        *graders.e1_understanding(runs),
        graders.e2_execution(runs, dw_path),
        graders.e2b_variants(base, variant_scores),
        graders.e3_package(runs),
        *graders.e4_stability(repeats, paraphrased),
        *graders.e5_questions(runs),
        graders.e6_safety(runs),
        graders.e7_dq(),
        graders.e8_operations(runs),
    ]


def main(argv: list[str]) -> int:
    with tempfile.TemporaryDirectory() as workdir:
        dw_path = argv[1] if len(argv) > 1 else str(Path(workdir) / "re.db")
        if len(argv) <= 1:
            build(dw_path)
        scores = asyncio.run(evaluate(dw_path, workdir))
    for s in scores:
        mark = "PASS" if s.passed else "FAIL"
        print(f"{mark:4}  {s.name:38} {s.value}  (≥ {s.threshold})  {s.detail}")
    return 0 if all(s.passed for s in scores) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
