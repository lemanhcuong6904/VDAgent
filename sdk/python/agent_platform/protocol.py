from __future__ import annotations

import asyncio
import inspect
import json
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, TextIO

AGENT_RUNNER_PROTOCOL = "agent-runner.v1"


@dataclass(frozen=True)
class AgentManifest:
    id: str
    version: str
    name: str
    description: str
    input_schema: Mapping[str, Any]
    tools: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    output_schema: Mapping[str, Any] | None = None
    model_profile: str | None = None
    accepts_delegation: bool = True
    limits: Mapping[str, int] = field(default_factory=dict)
    guardrails: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "apiVersion": "agent-plugin.v2",
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "requiredCapabilities": list(self.required_capabilities),
            "acceptsDelegation": self.accepts_delegation,
            "tools": list(self.tools),
            "inputSchema": dict(self.input_schema),
            "guardrails": list(self.guardrails),
        }
        if self.output_schema is not None:
            result["outputSchema"] = dict(self.output_schema)
        if self.model_profile is not None:
            result["modelProfile"] = self.model_profile
        if self.limits:
            result["limits"] = dict(self.limits)
        return result


@dataclass(frozen=True)
class AgentScope:
    user_id: str
    space_id: str
    task_id: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    trace_id: str | None = None


class _Rpc:
    def __init__(self, request_id: str, stdin: TextIO, stdout: TextIO):
        self.request_id = request_id
        self.stdin = stdin
        self.stdout = stdout

    def call(self, name: str, input_value: Any) -> Any:
        call_id = uuid.uuid4().hex
        _write(
            self.stdout,
            {
                "protocol": AGENT_RUNNER_PROTOCOL,
                "type": "tool_call",
                "request_id": self.request_id,
                "call_id": call_id,
                "name": name,
                "input": input_value,
            },
        )
        while True:
            line = self.stdin.readline()
            if not line:
                raise RuntimeError("Agent runner host closed stdin while waiting for a tool")
            message = _read(line)
            if message.get("protocol") != AGENT_RUNNER_PROTOCOL:
                raise RuntimeError("Unsupported host protocol")
            if message.get("type") == "cancel" and message.get("request_id") == self.request_id:
                raise RuntimeError("Agent run cancelled")
            if (
                message.get("type") == "tool_result"
                and message.get("request_id") == self.request_id
                and message.get("call_id") == call_id
            ):
                if message.get("ok"):
                    return message.get("output")
                raise RuntimeError(str(message.get("error") or "Tool call failed"))


class ToolClient:
    def __init__(self, rpc: _Rpc):
        self._rpc = rpc

    def call(self, name: str, input_value: Any) -> Any:
        return self._rpc.call(name, input_value)


class WarehouseClient:
    def __init__(self, tools: ToolClient):
        self._tools = tools

    def list_sources(self) -> Any:
        return self._tools.call("warehouse.list_sources", {})

    def describe(self, input_value: Any) -> Any:
        return self._tools.call("warehouse.describe_table", input_value)

    def describe_table(self, input_value: Any) -> Any:
        return self.describe(input_value)

    def query(self, input_value: Any) -> Any:
        return self._tools.call("warehouse.run_query", input_value)

    def run_query(self, input_value: Any) -> Any:
        return self.query(input_value)

    def list_tables(self, warehouse_id: str | None = None) -> Any:
        payload = {} if warehouse_id is None else {"warehouseId": warehouse_id}
        return self._tools.call("warehouse.list_tables", payload)

    def describe_dataset(self, dataset_id: str) -> Any:
        return self._tools.call("warehouse.describe_dataset", {"datasetId": dataset_id})

    def get_dataset_rows(self, dataset_id: str, offset: int = 0, limit: int = 50) -> Any:
        return self._tools.call(
            "warehouse.get_dataset_rows",
            {"datasetId": dataset_id, "offset": offset, "limit": limit},
        )


class ArtifactClient:
    def __init__(self, tools: ToolClient):
        self._tools = tools

    def read(self, artifact_id: str) -> Any:
        return self._tools.call("warehouse.describe_dataset", {"datasetId": artifact_id})

    def write(self, kind: str, input_value: Any) -> Any:
        return self._tools.call(f"artifacts.{kind}", input_value)


class AgentClient:
    def __init__(self, tools: ToolClient):
        self._tools = tools

    def catalog(self, capability: str | None = None) -> Any:
        payload = {} if capability is None else {"capability": capability}
        return self._tools.call("agents.catalog", payload)

    def delegate(self, input_value: Any) -> Any:
        return self._tools.call("agents.delegate", input_value)

    def send(
        self,
        message: str,
        *,
        agent: str | None = None,
        capability: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Queue a durable child run through the host policy boundary."""
        payload: dict[str, Any] = {"message": message}
        if agent is not None:
            payload["agent"] = agent
        if capability is not None:
            payload["capability"] = capability
        if idempotency_key is not None:
            payload["idempotencyKey"] = idempotency_key
        return self._tools.call("agents.send", payload)

    def wait(self, run_id: str, timeout_ms: int = 30_000) -> Any:
        return self._tools.call("agents.wait", {"runId": run_id, "timeoutMs": timeout_ms})

    def result(self, run_id: str) -> Any:
        return self._tools.call("agents.result", {"runId": run_id})


@dataclass(frozen=True)
class AgentContext:
    scope: AgentScope
    tools: ToolClient
    warehouse: WarehouseClient
    artifacts: ArtifactClient
    agents: AgentClient


class Agent(Protocol):
    manifest: AgentManifest

    def run(self, input_value: Any, context: AgentContext) -> Any:
        ...


def serve(agent: Agent, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    """Serve one Python agent over the versioned JSONL stdin/stdout protocol."""
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    while True:
        line = input_stream.readline()
        if not line:
            return
        try:
            request = _read(line)
            if request.get("protocol") != AGENT_RUNNER_PROTOCOL or request.get("type") != "run":
                raise RuntimeError("Expected an agent-runner.v1 run message")
            request_id = _required_string(request, "request_id")
            scope_value = request.get("scope")
            if not isinstance(scope_value, dict):
                raise RuntimeError("Run scope is required")
            scope = AgentScope(
                user_id=_required_string(scope_value, "userId"),
                space_id=_required_string(scope_value, "spaceId"),
                task_id=_optional_string(scope_value, "taskId"),
                run_id=_optional_string(scope_value, "runId"),
                parent_run_id=_optional_string(scope_value, "parentRunId"),
                trace_id=_optional_string(scope_value, "traceId"),
            )
            tools = ToolClient(_Rpc(request_id, input_stream, output_stream))
            context = AgentContext(
                scope=scope,
                tools=tools,
                warehouse=WarehouseClient(tools),
                artifacts=ArtifactClient(tools),
                agents=AgentClient(tools),
            )
            result = agent.run(request.get("input"), context)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            _write(
                output_stream,
                {
                    "protocol": AGENT_RUNNER_PROTOCOL,
                    "type": "result",
                    "request_id": request_id,
                    "ok": True,
                    "output": result,
                },
            )
        except Exception as error:  # Keep protocol errors inside the request boundary.
            request_id = request.get("request_id") if isinstance(request, dict) else None
            if isinstance(request_id, str):
                _write(
                    output_stream,
                    {
                        "protocol": AGENT_RUNNER_PROTOCOL,
                        "type": "result",
                        "request_id": request_id,
                        "ok": False,
                        "error": str(error),
                    },
                )
            else:
                raise


def _write(stream: TextIO, message: Mapping[str, Any]) -> None:
    stream.write(json.dumps(message, separators=(",", ":"), ensure_ascii=True) + "\n")
    stream.flush()


def _read(line: str) -> dict[str, Any]:
    value = json.loads(line)
    if not isinstance(value, dict):
        raise RuntimeError("Protocol message must be an object")
    return value


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise RuntimeError(f"Protocol field '{key}' must be a non-empty string")
    return result


def _optional_string(value: Mapping[str, Any], key: str) -> str | None:
    result = value.get(key)
    return result if isinstance(result, str) else None
