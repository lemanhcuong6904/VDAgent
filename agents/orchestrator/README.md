# orchestrator agent

Talks to Sales Ops: understands the question, plans steps for the other agents from their catalogs,
dispatches them with `send_to_agent`, handles failures and questions, and closes the run with a
Vietnamese summary citing artifact ids. Never writes SQL. Design: Orchestrator v4
(`docs/agent-a/orchestrator/`).

A Backend plugin (see [`agents/_template`](../_template/README.md) and the `vdagent_sdk` docstring):
`vdagent_orchestrator/__init__.py` exports `setup(api, opts)`, which registers the agent. Shared
pieces come from `vdagent_contracts` (`contracts/`: StepSpec, AgentReport, catalogs, envelopes) and
`vdagent_agentkit` (`agents/_shared/`: LLM router, MCP client, settings, test fakes).

## One turn

`agent.py` loads the run from `ctx.memory` (`run_state.py`, `records.py`) and routes the message:
a new question, a clarification answer, an answer to an agent's question or to the decision card, or
"go on". A new question then goes through:

| Stage | Modules |
|---|---|
| Understand (LLM 1), clarify rules A1–A6 | `llm1.py`, `intent.py`, `simple_router.py` |
| Plan (LLM 2), wiring, 12 checker rules, fallback plan | `llm2.py`, `planner.py`, `planning.py`, `wiring.py`, `checker.py`, `fallback.py`, `catalogs.py` |
| Dispatch in waves (D3: agents never forward to each other) | `dispatcher.py`, `states.py` |
| Failures: classify, propagate, replan, decision card, agent questions | `classify.py`, `propagate.py`, `replan.py`, `decision.py`, `inputs.py` |
| Close the run, summary, `run_state` / `run_summary` artifacts | `close.py`, `wording.py`, `lineage.py` |

Every LLM call of a question counts against `MAX_LLM_CALLS` (9); at most `MAX_REPLANS` (2) replans per
run. Prompts: `prompts/intent.md` (LLM 1), `prompts/plan.md` (LLM 2).

MCP tools granted by `mcp_tools` in `backend/config.yaml`: `get_user_context`,
`artifact_put` / `artifact_get` / `artifact_list` (writes `run_state`, `run_summary`),
`describe_dataset`, `get_dataset_rows`; plus `send_to_agent` to reach the other agents.

## Run

The Backend loads it at startup when `vdagent_orchestrator` is listed under `plugins:` in
`backend/config.yaml` (it is by default): `make backend` from the repo root. There is no separate
process.

Configure it in `agents/orchestrator/.env` (gitignored, see `.env.example`). The plugin reads the file
itself with `dotenv_values()`; its values win over the Backend's process environment. Without LLM
settings the plugin still loads, but serves only simple lookups with a fallback plan.

| Variable | |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` | OpenAI-compatible endpoint with structured output. |
| `LLM_TIMEOUT_S` | Per LLM call, default 120. |
| `LLM_REASONING_EFFORT` | Optional, e.g. `none` for reasoning models at temperature 0. |
| `FALLBACK_LLM_MODEL` (+ `FALLBACK_OPENAI_API_KEY`, `FALLBACK_OPENAI_BASE_URL`) | Optional second provider. |

## Test

```
uv run pytest agents/orchestrator
```
