from __future__ import annotations

import json
from pathlib import Path

from .contracts import ChartTaskInput
from .schema import parse_chart_task

TASKS_FILE = Path(__file__).parent / "demo" / "tasks.json"


def _task(raw: dict) -> ChartTaskInput:
    return parse_chart_task(raw)


def _raw_tasks() -> list[dict]:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]


def scenario_names() -> tuple[str, ...]:
    return tuple(task["name"] for task in _raw_tasks())


def load_demo_task(name: str) -> ChartTaskInput:
    for task in _raw_tasks():
        if task["name"] == name:
            return _task(task)
    raise KeyError(f"unknown chart demo task {name!r}")
