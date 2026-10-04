# AgentRunner protocol

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../README.md).

Process agents speak one protocol: `agent-runner.v2`, newline-delimited JSON over stdin/stdout. The
host starts one process per invocation. Schema: `schemas/agent-protocol.schema.json` (type
`AgentProtocol`); host runner `src/agent-runner.ts` (`ProcessAgentRunner`); Python SDK `sdk/python/agent_platform`
(`serve`). External manifests (`AGENT_EXTERNAL_MANIFESTS`) run on v2; `"protocol"` may be omitted.

```text
host -> agent: invoke | port_result | cancel
agent -> host: port_call | event | checkpoint | wait | result
```

```json
{"protocol":"agent-runner.v2","type":"invoke","request_id":"run-123","agent_id":"team.python.summary",
 "input":{"prompt":"..."},"scope":{"user_id":"u1","space_id":"s1","run_id":"run-123"},
 "tools":["warehouse.run_query"]}
```

Every `port_call` goes through the shared host port factory (`src/ports/host-factory.ts`), the same
one in-process `AgentModule` agents use. Port `tools` with the tool name as `operation`; the host
checks the manifest grant and the pool allowlist on every call, and checks `sequence`/`call_id`
correlation. A failed write tool stays `unknown`, never a clean failure. The parser keeps unknown
fields for forward compatibility; schema validity is not authorization.

The agent process never receives a database connection, Docker socket, provider secret, or internal
module reference. The runner also strips credential-like environment variables before spawning the
process. It receives only scope and declared tool names. The host owns authorization,
timeouts, cancellation, quotas, tracing, retry classification and artifact ownership.

For agent-to-agent work, declare the platform ports in the manifest and use the Python SDK. The
available ports are `agents.catalog`, `agents.send`, `agents.wait`, and `agents.result`; each call
is checked against the current task, tenant, allowed edge, depth, fan-out, payload and quota policy.
`agents.send` returns a durable `runId`; `wait` may return a non-terminal snapshot when its timeout
expires, and `result` can be called later. The Python process never opens a direct connection to
another agent or to the platform database.

Python quick start:

```sh
uv sync --project agents
```

See the Python SDK guide (`sdk/python/README.md`, removed in Phase 4; Git history `aed2917`) for a complete agent and external manifest.
Set `AGENT_EXTERNAL_MANIFESTS` to register the manifest. A malformed manifest or unsupported protocol
version is rejected before the agent can receive traffic.
