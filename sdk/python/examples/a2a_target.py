from agent_platform import AgentContext, AgentManifest, serve


class TargetAgent:
    manifest = AgentManifest(
        id="example.python.target",
        version="1.0.0",
        name="Python A2A target",
        description="Returns a deterministic response for the A2A bridge smoke test.",
        capabilities=("example.a2a.target",),
        input_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string", "minLength": 1, "maxLength": 4000}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
    )

    def run(self, value: dict, context: AgentContext) -> dict:
        return {"agent": self.manifest.id, "prompt": value["prompt"], "parent": context.scope.parent_run_id}


if __name__ == "__main__":
    serve(TargetAgent())
