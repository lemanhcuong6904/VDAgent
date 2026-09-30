"""The one-request golden over the public REST API, with an explicit idempotency key (F-03, F-08, F-11)."""

from __future__ import annotations

import re
import uuid

import httpx

from conftest import ALICE, BOB, QUESTION, save, wait_task


def _answer(api: httpx.Client, task_id: str) -> str:
    history = api.get("/api/agents/orchestrator/messages", headers=ALICE).json()["messages"]
    return [m for m in history if m["task_id"] == task_id and m["role"] == "assistant" and m["content"]][-1]["content"]


def test_golden_request(api: httpx.Client) -> None:
    key = f"ws7-{uuid.uuid4().hex}"
    first = api.post("/api/agents/orchestrator/messages", json={"content": QUESTION}, headers={**ALICE, "Idempotency-Key": key})
    assert first.status_code == 202, first.text
    task_id = first.json()["task_id"]
    retry = api.post("/api/agents/orchestrator/messages", json={"content": QUESTION}, headers={**ALICE, "Idempotency-Key": key})
    assert retry.status_code == 200 and retry.json() == {**first.json(), "deduplicated": True}  # F-11: no second run
    clash = api.post("/api/agents/orchestrator/messages", json={"content": "khác"}, headers={**ALICE, "Idempotency-Key": key})
    assert clash.status_code == 409

    detail = wait_task(api, task_id)
    save("golden_task.txt", task_id)
    save("golden_task.json", detail)
    task = detail["task"]
    assert (task["status"], task["outcome"]) in {("completed", "completed"), ("completed", "partial")}  # F-03
    assert [i["agent"] for i in detail["invocations"]] == ["orchestrator", "data", "insight", "compare", "chart", "report"]
    assert all(i["status"] == "completed" for i in detail["invocations"])

    answer = _answer(api, task_id)
    save("golden_answer.md", answer)
    for needle in ("SNAP-2026-09-28", "sc-1", "138 ngày", "trung vị 61 ngày", "72.500.000 VND/m²", "64.500.000 VND/m²",
                   "12,40%", "5 căn", "B-11"):
        assert needle in answer, needle
    assert "một phần" in answer if task["outcome"] == "partial" else True  # a PARTIAL run says so
    peers = re.search(r"5 căn \(([^)]*)\)", answer)
    assert peers and len(peers.group(1).split(", ")) == 5


def test_report_api_and_isolation(api: httpx.Client) -> None:
    reports = api.get("/api/reports", headers=ALICE).json()
    assert reports, "no report delivered"
    report_id = reports[0]["id"]
    body = api.get(f"/api/reports/{report_id}", headers=ALICE)
    assert body.status_code == 200
    save("report.json", body.json())
    assert "{{chart_spec:" in body.json()["markdown"]  # pinned embeds; the UI renders them (browser test)
    assert api.get(f"/api/reports/{report_id}", headers=BOB).status_code == 404
    assert api.get("/api/reports", headers=BOB).json() == []
    assert api.get("/api/reports", headers={}).status_code == 401


def test_same_text_without_key_is_a_new_run(api: httpx.Client) -> None:
    a = api.post("/api/agents/orchestrator/messages", json={"content": "Căn A12-08 có DOM bao nhiêu?"}, headers=ALICE).json()
    b = api.post("/api/agents/orchestrator/messages", json={"content": "Căn A12-08 có DOM bao nhiêu?"}, headers=ALICE).json()
    assert a["task_id"] != b["task_id"] and not a["deduplicated"] and not b["deduplicated"]
    for t in (a, b):
        wait_task(api, t["task_id"])


def test_unauthorized_unit_fails_honestly(api: httpx.Client) -> None:
    started = api.post("/api/agents/orchestrator/messages", json={"content": QUESTION}, headers=BOB).json()
    task = wait_task(api, started["task_id"], headers=BOB)["task"]
    assert (task["status"], task["outcome"]) == ("failed", "failed")  # F-03: never shown as success
