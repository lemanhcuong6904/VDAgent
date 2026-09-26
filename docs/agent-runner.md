# AgentRunner protocol

`agent-runner.v1` is the language-neutral boundary for team agents. The host starts one process per
invocation and exchanges newline-delimited JSON on stdin/stdout. Python is the reference SDK; a
TypeScript agent may use the same protocol when process isolation is required.

The host sends one `run` message:

```json
{
  "protocol": "agent-runner.v1",
  "type": "run",
  "request_id": "run-123",
  "agent_id": "team.python.summary",
  "agent_version": "1.0.0",
  "input": {"prompt": "..."},
  "scope": {"userId": "u1", "spaceId": "s1", "runId": "run-123"},
  "tools": ["warehouse.run_query"]
}
```

The agent returns `result` or can request a host tool. Every tool call is authorized again by the
host and is correlated with both `request_id` and `call_id`:

```text
host -> agent: run | cancel
agent -> host: tool_call | event | result
host -> agent: tool_result
```

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
pip install -e sdk/python
```

See [the Python SDK guide](../sdk/python/README.md) for a complete agent and external manifest.
Set `AGENT_EXTERNAL_MANIFESTS` to register the manifest. A malformed manifest or unsupported protocol
version is rejected before the agent can receive traffic.
