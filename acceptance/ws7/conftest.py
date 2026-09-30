"""WS7 acceptance suite (F-06): black-box checks against a running offline stack started by run.sh.

Environment: WS7_BASE_URL (required, else every test skips), WS7_DB (a copy of the stack's backend.db for the lineage
checks), WS7_OUT (evidence directory), WS7_KILLED_TASK (a task whose backend was killed mid-run, for the restart check).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

QUESTION = "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo."
ALICE, BOB = {"X-User-Id": "u_000000000001"}, {"X-User-Id": "u_000000000002"}  # seeded demo users (PRJ-X, PRJ-Y)
BASE = os.environ.get("WS7_BASE_URL", "")
OUT = Path(os.environ.get("WS7_OUT", "acceptance/ws7/out"))


def need(var: str) -> str:
    value = os.environ.get(var, "")
    if not value:
        pytest.skip(f"{var} is not set (run acceptance/ws7/run.sh)")
    return value


@pytest.fixture(scope="session")
def api() -> httpx.Client:
    need("WS7_BASE_URL")
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=BASE, timeout=30) as client:
        yield client


def wait_task(api: httpx.Client, task_id: str, headers: dict[str, str] = ALICE, timeout: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = api.get(f"/api/tasks/{task_id}", headers=headers).json()
        if body["task"]["status"] != "running":
            return body
        time.sleep(0.5)
    raise AssertionError(f"{task_id} still running after {timeout}s")


def save(name: str, data: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2))


def golden_task() -> str:
    path = OUT / "golden_task.txt"
    if not path.exists():
        pytest.skip("run test_api_golden.py first")
    return path.read_text().strip()
