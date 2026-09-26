from agent_platform import AgentContext, AgentManifest, serve


class SenderAgent:
    manifest = AgentManifest(
        id="example.python.sender",
        version="1.0.0",
        name="Python A2A sender",
        description="Sends a durable message to another Python agent.",
        capabilities=("example.a2a.sender",),
        tools=("agents.send", "agents.wait", "agents.result"),
        input_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string", "minLength": 1, "maxLength": 4000}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
    )

    def run(self, value: dict, context: AgentContext) -> dict:
        receipt = context.agents.send(
            value["prompt"], agent="example.python.target", idempotency_key="example-a2a"
        )
        waited = context.agents.wait(receipt["runId"], timeout_ms=15_000)
        return {"receipt": receipt, "wait": waited, "result": context.agents.result(receipt["runId"])}


if __name__ == "__main__":
    serve(SenderAgent())
