"""A run whose backend was killed mid-flight is reported as interrupted after the restart (F-04)."""

from __future__ import annotations

import json
import sqlite3

import httpx

from conftest import need, save, wait_task


def test_killed_run_is_interrupted_not_running(api: httpx.Client) -> None:
    detail = wait_task(api, need("WS7_KILLED_TASK"), timeout=10)
    save("restart_task.json", detail)
    task = detail["task"]
    if task["status"] == "completed":  # the run beat the kill: nothing was interrupted
        assert task["outcome"] in {"completed", "partial"}
        return
    assert (task["status"], task["outcome"]) == ("failed", "interrupted")
    assert any(i["status"] == "failed" and "restart" in (i["error"] or "") for i in detail["invocations"])


def test_killed_run_state_is_reconciled() -> None:
    task_id = need("WS7_KILLED_TASK")
    conn = sqlite3.connect(need("WS7_DB"))
    status = conn.execute("SELECT status, outcome FROM tasks WHERE id = ?", (task_id,)).fetchone()
    rows = conn.execute("SELECT payload_json FROM artifacts WHERE run_id = ? AND artifact_type = 'run_state' ORDER BY version",
                        (task_id,)).fetchall()
    states = [json.loads(p)["status"] for (p,) in rows]
    save("restart_run_state.json", {"task": list(status), "run_state_versions": states})
    if status[0] == "completed" or not rows:
        return  # the run completed first, or it was killed before its first run_state
    assert states[-1] == "interrupted"
