"""Test doubles for the WS5 DAG executor: a ctx that enforces the Backend's call rules and an in-memory artifact store.

`FakeCtx.call_agent` accepts only an unresolved `send_to_agent` tool call of the latest assistant step (engine R3/R4),
and `emit_tool_result` only after the call has returned — the same contract `backend/vdagent_backend/engine` enforces.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from vdagent_contracts.reports import AgentReport, render_agent_report
from vdagent_sdk import SEND_TO_AGENT, McpEndpoint, ToolCall

ALICE = "u_000000000001"
SNAP, SEM = "SNAP-2026-09-28", "sc-1"
Handler = Callable[[dict[str, Any]], Awaitable[str]]


class FakeTools:
    def __init__(self, user: str = ALICE, projects: tuple[str, ...] = ("PRJ-X",)) -> None:
        self.arts: dict[tuple[str, int], dict[str, Any]] = {}
        self.user, self.projects, self.n = user, projects, 0
        self.calls: list[str] = []

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        if name == "get_user_context":
            return {"user_id": self.user, "authorized_scope": {"project_ids": list(self.projects), "zone_ids": []}}
        if name == "artifact_get":
            key = (args["artifact_id"], args.get("version") or self._latest(args["artifact_id"]))
            if key not in self.arts:
                raise LookupError("error: artifact not found")
            return json.loads(json.dumps(self.arts[key]))
        if name == "artifact_put":
            return self.put(json.loads(args["draft_json"]), run_id=args.get("run_id", "t_1"))
        if name == "artifact_list":
            latest: dict[str, dict[str, Any]] = {}
            for (aid, _), env in sorted(self.arts.items()):
                if args.get("run_id") and env["run_id"] != args["run_id"]:
                    continue
                if args.get("artifact_type") and env["artifact_type"] != args["artifact_type"]:
                    continue
                latest[aid] = env
            return {"artifacts": [{k: v for k, v in e.items() if k != "payload"} for e in latest.values()]}
        raise AssertionError(f"unexpected tool {name}")

    def _latest(self, artifact_id: str) -> int:
        return max((v for a, v in self.arts if a == artifact_id), default=1)

    def put(self, draft: dict[str, Any], run_id: str = "t_1") -> dict[str, Any]:
        aid = draft.pop("artifact_id", None)
        if aid is None:
            self.n += 1
            aid, version = f"art_{self.n:04d}", 1
        else:
            version = self._latest(aid) + 1
        body = json.dumps(draft["payload"], sort_keys=True)
        env = {**draft, "artifact_id": aid, "version": version, "run_id": run_id, "task_id": run_id,
               "content_hash": hashlib.sha256((draft["artifact_type"] + body).encode()).hexdigest()}
        env.setdefault("snapshot_refs", [SNAP])
        env.setdefault("semantic_config_version", SEM)
        env.setdefault("input_artifact_refs", [])
        env.setdefault("limitations", [])
        self.arts[(aid, version)] = env
        return env

    def ref(self, env: dict[str, Any]) -> dict[str, Any]:
        return {"artifact_id": env["artifact_id"], "version": env["version"], "artifact_type": env["artifact_type"],
                "content_hash": env["content_hash"]}


class FakeCtx:
    def __init__(self, text: str, handlers: dict[str, Handler], task_id: str = "t_1") -> None:
        self.invocation_id, self.task_id, self.user_id = "inv_orch", task_id, ALICE
        self.summary, self.max_steps = "", 12
        self.history = [{"role": "user", "content": f"[from: user] {text}"}]
        self.peers: list[Any] = []
        self.mcp = McpEndpoint(url="http://mcp.test/mcp", token="tok")
        self.handlers = handlers
        self.steps: list[tuple[str, list[ToolCall]]] = []
        self.results: dict[str, str] = {}
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._open: set[str] = set()
        self._called: set[str] = set()
        self.outcome: str | None = None

    def report_outcome(self, outcome: str) -> None:
        assert outcome in ("completed", "partial", "failed")
        self.outcome = outcome

    async def emit_assistant(self, content: str, tool_calls: Any = ()) -> None:
        assert not self._open, f"R5: unresolved tool calls {self._open} before a new assistant step"
        calls = list(tool_calls)
        self.steps.append((content, calls))
        self._open = {c.id for c in calls}

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:
        last = {c.id: c for c in self.steps[-1][1]} if self.steps else {}
        assert tool_call_id in last and last[tool_call_id].name == SEND_TO_AGENT, "R4: not a send_to_agent call of the last step"
        assert tool_call_id not in self._called, "R4: called twice"
        self._called.add(tool_call_id)
        step = json.loads(message)
        self.sent.append((target, step))
        handler = self.handlers.get(target)
        if handler is None:
            return f"error: unknown agent '{target}'"
        return await handler(step)

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        assert tool_call_id in self._open, "R3: not an unresolved tool call of the last step"
        self._open.discard(tool_call_id)
        self.results[tool_call_id] = content

    @property
    def answer(self) -> str:
        content, calls = self.steps[-1]
        assert calls == []
        return content


def report(step: dict[str, Any], state: str = "completed", refs: list[dict[str, Any]] | None = None,
           warnings: list[str] | None = None, error: dict[str, Any] | None = None, partial: bool = False) -> str:
    body = AgentReport.model_validate({
        "run_id": step["run_id"], "step_id": step["step_id"], "idempotency_key": step["idempotency_key"],
        "state": state, "partial": partial, "artifact_refs": refs or [], "snapshot_id": step.get("snapshot_id"),
        "semantic_config_version": step.get("semantic_config_version"), "warnings": warnings or [], "error": error,
    })
    return render_agent_report(f"{step['step_id']}: {state}", body)


def golden_handlers(tools: FakeTools, barrier: asyncio.Barrier | None = None, log: list[str] | None = None,
                    fail: set[str] = frozenset()) -> dict[str, Handler]:
    """Scripted agents over `tools`; `fail` names agents that answer `failed`."""
    log = log if log is not None else []

    def failed(step: dict[str, Any], agent: str) -> str:
        return report(step, "failed", error={"code": f"{agent.upper()}_BROKEN", "message": "scripted failure"})

    async def data(step: dict[str, Any]) -> str:
        log.append("data:start")
        if "data" in fail:
            return failed(step, "data")
        ds = tools.put({"artifact_type": "dataset", "schema_version": "re_dataset@1", "status": "VALID", "producer": {"agent": "data"},
                        "payload": {"population": {"subject_unit_key": "U-PRJ-X-A12-08"},
                                    "tables": {"dim_unit_master": [{"unit_key": "U-PRJ-X-A12-08", "unit_code": "A12-08", "project_key": "PRJ-X"}]}},
                        "limitations": ["SYNTHETIC_SOURCE:net_area_m2"]}, run_id=step["run_id"])
        refs = [tools.ref(ds)]
        for kind in ("metric", "dq"):
            env = tools.put({"artifact_type": kind, "schema_version": f"re_{kind}@1", "status": "PARTIAL", "producer": {"agent": "data"},
                             "payload": {}, "input_artifact_refs": [tools.ref(ds)], "limitations": ["METRIC_UNAVAILABLE:discount_pct"]},
                            run_id=step["run_id"])
            refs.append(tools.ref(env))
        log.append("data:end")
        return report(step, refs=refs, partial=True, warnings=["METRIC_UNAVAILABLE:discount_pct"])

    async def analysis(step: dict[str, Any], agent: str, outputs: list[tuple[str, str, dict[str, Any]]]) -> str:
        log.append(f"{agent}:start")
        if barrier is not None:
            async with asyncio.timeout(2):
                await barrier.wait()  # both analysis agents must be running at the same time
        if agent in fail:
            log.append(f"{agent}:end")
            return failed(step, agent)
        ds_ref = step["input_refs"][0]
        refs = []
        for kind, schema, payload in outputs:
            env = tools.put({"artifact_type": kind, "schema_version": schema, "status": "PARTIAL", "producer": {"agent": agent},
                             "payload": payload, "input_artifact_refs": [ds_ref, *refs], "limitations": ["X"]}, run_id=step["run_id"])
            refs.append(tools.ref(env))
        log.append(f"{agent}:end")
        return report(step, refs=refs, partial=True)

    async def insight(step: dict[str, Any]) -> str:
        return await analysis(step, "insight", [("insight", "insight.v2", {"insight": {"insights": [
            {"insight_id": "I1", "cause_code": "OVERPRICED_VS_PEER", "subject": {"id": "U-PRJ-X-A12-08", "label": "A12-08"},
             "claim": {"rendered_text": "Căn A12-08 tồn 138 ngày", "numeric_bindings": [
                 {"slot": "dom", "value": "138", "unit": "DAY"}, {"slot": "spread", "value": "12.40", "unit": "PCT"}]}}]}})])

    async def compare(step: dict[str, Any]) -> str:
        return await analysis(step, "compare", [
            ("peer_definition", "peer_definition@1", {"peers": [{"entityCode": c} for c in ("A12-11", "A10-02", "A14-03", "B09-05", "B11-07")]}),
            ("comparison", "comparison@1", {"subject": {"entityCode": "A12-08", "entityId": "U-PRJ-X-A12-08"}, "metrics": [
                {"metric": "dom", "unit": "days", "subjectValue": 138, "benchmark": {"stat": "median", "value": 61, "n": 5}, "pctGap": "126.23"},
                {"metric": "net_asking_price_per_m2", "unit": "VND/m2", "subjectValue": 72500000,
                 "benchmark": {"stat": "median", "value": 64500000, "n": 5}, "pctGap": "12.4"}]}),
        ])

    async def chart(step: dict[str, Any]) -> str:
        log.append("chart:start")
        if "chart" in fail:
            return failed(step, "chart")
        ds_ref = next(r for r in step["input_refs"])  # any upstream: chart pins the dataset it inherits
        env = tools.put({"artifact_type": "chart_spec", "schema_version": "chart_spec@1", "status": "PARTIAL", "producer": {"agent": "chart"},
                         "payload": {"chart_type": "bar"}, "input_artifact_refs": [ds_ref], "limitations": ["X"]}, run_id=step["run_id"])
        log.append("chart:end")
        return report(step, refs=[tools.ref(env)], partial=True)

    async def report_agent(step: dict[str, Any]) -> str:
        log.append("report:start")
        if "report" in fail:
            return failed(step, "report")
        env = tools.put({"artifact_type": "report", "schema_version": "report@1", "status": "PARTIAL", "producer": {"agent": "report"},
                         "payload": {"markdown": "# R", "delivery": {"report_id": "rp_fake"}},
                         "input_artifact_refs": list(step["input_refs"]), "limitations": ["X"]}, run_id=step["run_id"])
        log.append("report:end")
        return report(step, refs=[tools.ref(env)], partial=True)

    return {"data": data, "insight": insight, "compare": compare, "chart": chart, "report": report_agent}
