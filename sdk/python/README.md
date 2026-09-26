# Python Agent SDK

This package lets a team write an agent in Python without importing the TypeScript API, database
client, PiRuntime, or private backend modules. The host starts the agent as an isolated process and
speaks `agent-runner.v1` JSONL over stdin/stdout.

Install locally with `pip install -e sdk/python`, then define a manifest and a `run` method:

```python
from agent_platform import AgentContext, AgentManifest, serve


class SummaryAgent:
    manifest = AgentManifest(
        id="team.python.summary",
        version="1.0.0",
        name="Python Summary",
        description="Summarizes verified warehouse evidence.",
        capabilities=("dataset.insight",),
        tools=(
            "warehouse.run_query",
            "agents.catalog",
            "agents.send",
            "agents.wait",
            "agents.result",
        ),
        input_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string", "minLength": 1}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
    )

    def run(self, input_value: dict, context: AgentContext) -> dict:
        sources = context.warehouse.list_sources()
        receipt = context.agents.send(
            "Verify the most relevant finding.", capability="dataset.insight"
        )
        context.agents.wait(receipt["runId"])
        finding = context.agents.result(receipt["runId"])
        return {"answer": input_value["prompt"], "sources": sources, "finding": finding}


if __name__ == "__main__":
    serve(SummaryAgent())
```

Register a JSON manifest pointing to the executable module. The manifest is validated by the host;
the Python process receives only its scoped input and declared tool calls:

```json
{
  "apiVersion": "agent-plugin.v2",
  "id": "team.python.summary",
  "version": "1.0.0",
  "name": "Python Summary",
  "description": "Summarizes verified warehouse evidence.",
  "capabilities": ["dataset.insight"],
  "tools": ["warehouse.run_query", "agents.catalog", "agents.send", "agents.wait", "agents.result"],
  "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]},
  "command": "python",
  "args": ["-m", "my_agent"]
}
```

Set `AGENT_EXTERNAL_MANIFESTS=agents/python-summary.json`. The process cannot access PostgreSQL or
Docker through the protocol; warehouse, artifact, and agent-to-agent access remains subject to the
host ToolPool policy. Use only declared tools, and treat every model/tool result as untrusted data.

The `examples/a2a_sender.py` and `examples/a2a_target.py` pair demonstrates durable Python-to-Python
messaging with `send`, `wait`, and `result`. Their manifests can be enabled together for a local
bridge smoke test.
