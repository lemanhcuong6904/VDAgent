# insight agent

Interprets results — trends, anomalies, drivers — each finding backed by a dataset id; may ask data or compare.

A Backend plugin: the Backend imports this package at startup and runs the agent's turns in its own
process; the agent reports every step through the `ctx` it receives (to build one, see
[`agents/_template`](../_template/README.md)).
`vdagent_insight/__init__.py` exports `setup(api, opts)`, which registers the agent. The brain is a
LangChain 1.x agent (`create_agent`) with its own long-term memory:

- `agent.py`: builds the agent per turn with two middlewares; `tools.py`: MCP tools (from
  `mcp_client.py`) as LangChain tools, plus `send_to_agent`.
- `bridge.py` (`CtxBridge`): maps LangChain's loop onto the turn contract (emits steps and results,
  routes `send_to_agent` through `ctx.call_agent`, enforces the step budget).
- `memory.py` (`MemoryMiddleware`): before the turn, embeds the request and recalls the nearest
  earlier findings for this user from `ctx.memory` into the system prompt; after the answer,
  extracts at most 3 durable findings (`prompts/extract.md`), skips near-duplicates (cosine
  distance < 0.1) and saves the rest with their embeddings. Memory failures never fail a turn.

Prompts: role `prompts/system.md`, summariser `prompts/compact.md`, memory extraction
`prompts/extract.md`.

MCP tools granted by the Backend (`backend/vdagent_backend/mcp/tools.py`): `query_datasets`, `describe_dataset`, `get_dataset_rows`;
plus `send_to_agent` to reach the other agents.

## Run

The Backend loads it at startup when `vdagent_insight` is listed under `plugins:` in
`backend/config.yaml` (it is by default): `make backend` from the repo root. There is no separate
process.

Configure it in `agents/insight/.env` (gitignored). The plugin reads the file itself with
`dotenv_values()`; its values win over the Backend's process environment. A missing required
variable makes the plugin fail to load: the Backend logs `plugin vdagent_insight failed: …` and starts
without this agent.

| Variable | |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` | Required. OpenAI-compatible endpoint with tool calling. |
| `LLM_TIMEOUT_S` | Per LLM call, default 120. |
| `EMBED_MODEL` | Embedding model for memory on the same endpoint, default `openai/text-embedding-3-small`. |

## Test

```
uv run pytest agents/insight
```
