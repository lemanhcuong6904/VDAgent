# compare agent

Compares datasets, periods and segments (deltas, % change, rankings) with `query_datasets`; may ask data for missing data.

A Backend plugin: the Backend imports this package at startup and runs the agent's turns in its own
process; the agent reports every step through the `ctx` it receives (to build one, see
[`agents/_template`](../_template/README.md)).
`vdagent_compare/__init__.py` exports `setup(api, opts)`, which registers the agent. The brain is a thin
tool-calling loop over LiteLLM (`agent.py`, `llm.py`, `mcp_client.py`); its role prompt is
`vdagent_compare/prompts/system.md`, the summariser prompt `prompts/compact.md`.

MCP tools granted by `mcp_tools` in `backend/config.yaml`: `query_datasets`, `describe_dataset`, `get_dataset_rows`;
plus `send_to_agent` to reach the other agents.

## Run

The Backend loads it at startup when `vdagent_compare` is listed under `plugins:` in
`backend/config.yaml` (it is by default): `make backend` from the repo root. There is no separate
process.

Configure it in `agents/compare/.env` (gitignored). The plugin reads the file itself with
`dotenv_values()`; its values win over the Backend's process environment. A missing required
variable makes the plugin fail to load: the Backend logs `plugin vdagent_compare failed: …` and starts
without this agent.

| Variable | |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` | Required. OpenAI-compatible endpoint with tool calling. |
| `LLM_TIMEOUT_S` | Per LLM call, default 120. |

## Test

```
uv run pytest agents/compare
```
