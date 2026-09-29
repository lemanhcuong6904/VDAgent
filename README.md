# vdagent

A proof-of-concept multi-agent analytics assistant. A user asks questions about a retail sales
warehouse; five LLM agents (orchestrator, data, compare, insight, report) collaborate by messaging
each other through the Backend, which also serves the React UI and an MCP tool server. The agents
are **plugins**: the Backend imports the modules listed in `backend/config.yaml` at startup, calls
their `setup(api, opts)` (like Neovim / lazy.nvim), and runs their turns in its own process.

- Design: [`docs/superpowers/specs/2026-09-24-vdagent-design.md`](docs/superpowers/specs/2026-09-24-vdagent-design.md)
- Agent template design: [`docs/superpowers/specs/2026-09-24-agent-template-design.md`](docs/superpowers/specs/2026-09-24-agent-template-design.md)
- Agents as plugins: [`docs/superpowers/specs/2026-09-26-agent-plugins-design.md`](docs/superpowers/specs/2026-09-26-agent-plugins-design.md)
- Agents beyond a ReAct loop: [`docs/superpowers/specs/2026-09-28-agent-freedom-design.md`](docs/superpowers/specs/2026-09-28-agent-freedom-design.md)
- Building an agent plugin: [`agents/_template/README.md`](agents/_template/README.md)

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.12 is picked up from `.python-version`), GNU make, Node 22 for the frontend.
- First time only:

  ```
  uv sync
  for a in orchestrator data compare insight report; do cp -n agents/$a/.env.example agents/$a/.env; done
  ```

  Then fill in `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `LLM_MODEL` in each `agents/<name>/.env`
  (see [Environment variables](#environment-variables)).

## Plugins

`backend/config.yaml` lists the agent plugins, loaded in order when the Backend starts:

```yaml
plugins:
  - module: vdagent_orchestrator
  - module: vdagent_data
    opts: {}          # optional, free-form: handed to the plugin's setup() as a dict
  - module: vdagent_report
    enabled: false    # optional toggle
```

- A plugin is an importable Python package in the Backend's environment (here: a uv workspace
  member under `agents/`) whose top-level module exports `setup(api, opts)`. `setup` registers one
  or more agents (`api.register_agent(name=…, description=…, agent=…)`) and optional shutdown hooks.
- Plugins depend only on `vdagent_sdk` (`sdk/`), which defines the interface the Backend expects:
  `Agent` (`invoke(ctx)`, `compact(...)`), `InvocationContext`, `PluginAPI`, and the turn rules
  R1–R11 in its docstring. How an agent thinks (framework, model, tool loop, MCP client, memory) is
  up to the plugin; see [Agents are different programs](#agents-are-different-programs).
- **A plugin that fails to load** (import error, missing setting, bad registration) is logged as
  `plugin <module> failed: …` and skipped; the Backend starts with the others. Its agent is absent
  from the UI and from every other agent's peer list.
- Plugins share the Backend's process and event loop: a plugin must not block the loop (R10) and
  must not write `os.environ` (R11).
- To add one: copy `agents/_template` (see its README), add the folder to the workspace in the
  root `pyproject.toml`, `uv sync`, and list its module under `plugins:`.

## Agents are different programs

The Backend runs every agent through the same `invoke(ctx)`; what happens inside is the agent
team's choice. Three agents are plain ReAct loops, two are not:

| Agent | Built with | Beyond a ReAct loop | What the Backend sees |
|---|---|---|---|
| orchestrator, data, compare | LiteLLM tool loop | nothing | assistant steps, tool results |
| insight | LangChain `create_agent` + middleware | recalls earlier findings by vector search, extracts and saves new ones, skips near-duplicates ([README](agents/insight/README.md)) | the same, plus `ctx.memory` rows |
| report | LangGraph `StateGraph` | every draft is judged by Jev, a decisions model (not a chat model); one revision edge driven by its typed verdict ([README](agents/report/README.md)) | only the final, assessed answer |

Agent memory lives in `backend.db` (`memories`, keyword search via FTS5, vector search via
sqlite-vec), scoped to one user and one agent. The Backend stores and ranks notes; the agent
computes the embeddings and decides what to save and recall (`ctx.memory`, SDK rule R1).

## Environment variables

Each component reads its own `.env` file. Every `.env` is gitignored and excluded from Docker
images; commit changes to the `.env.example` next to it instead.

| File | Needed? | Create it with |
|---|---|---|
| `agents/<name>/.env`, one per agent plugin | **Yes**, for each of the five agents | `cp agents/<name>/.env.example agents/<name>/.env`, then fill in the LLM settings |
| `backend/.env` | No: the Backend runs on `backend/config.yaml` alone | `cp backend/.env.example backend/.env`, then uncomment what you need |

### Agent plugins (`agents/<name>/.env`)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | API key for the model endpoint. |
| `OPENAI_BASE_URL` | yes | — | Base URL of an OpenAI-compatible endpoint, e.g. `https://…/v1`. |
| `LLM_MODEL` | yes | — | Model name served by that endpoint. It **must support tool calling**. |
| `LLM_TIMEOUT_S` | no | `120` | Timeout per LLM call, in seconds (must be > 0). |
| `EMBED_MODEL` | no (insight only) | `openai/text-embedding-3-small` | Embedding model for insight's memory, on the same endpoint. |
| `JUDGE_MODEL` | no (report only) | `typesafe/jev-1.13` | Jev model for report's quality gate, called with `OPENAI_API_KEY`. |
| `JEV_DECISIONS_URL` | no (report only) | `https://openrouter.ai/api/alpha/decisions` | Decisions endpoint serving Jev. |

The five agents need the same required variables. They may share one model or each use their own.

- **Who reads it:** each plugin reads its own file in `setup()` with `dotenv_values()`; nothing is
  loaded into the Backend's `os.environ`, so plugins cannot see or overwrite each other's keys.
- **Precedence:** the plugin's `.env` wins over the Backend's process environment, so a key
  exported in your shell cannot shadow the one in the plugin's file.
- **Missing required variable:** that plugin fails to load (`plugin vdagent_<name> failed:
  missing required environment variable …`); the Backend still starts.

### Backend (`backend/.env`, optional)

Each variable overrides the matching key of `backend/config.yaml`. The process environment wins
over the file.

| Variable | Default (`config.yaml`) | Meaning |
|---|---|---|
| `VDAGENT_MCP_PUBLIC_URL` | `http://localhost:8000/mcp` | MCP URL handed to agent plugins (their MCP clients connect to this Backend). |
| `VDAGENT_BACKEND_DB` | `./var/backend.db` | Backend SQLite file (relative to where the backend is started). |
| `VDAGENT_WAREHOUSE_DB` | `./var/warehouse.db` | Warehouse SQLite file. |
| `VDAGENT_FRONTEND_DIST` | `./frontend/dist` | Built frontend, served at `/` if it exists. |
| `VDAGENT_MAX_DEPTH` | `4` | Maximum agent-call depth. |
| `VDAGENT_MAX_STEPS` | `12` | Assistant steps per turn (`ctx.max_steps`). |
| `VDAGENT_CONFIG` | `backend/config.yaml` | Which YAML to load. Set it in the shell: it has no effect inside `backend/.env`, which is looked up next to the chosen config file. |

`HOST` (for `make backend HOST=0.0.0.0`) is a make variable, not an environment setting: it is the
interface the HTTP server (UI, API, MCP) binds to.

## Makefile usage

| Target | Does |
|---|---|
| `make` / `make help` | Lists the targets. |
| `make backend` | Starts the backend (API, SSE, MCP, built UI) on http://localhost:8000 with the agent plugins listed in `backend/config.yaml`. `HOST=0.0.0.0` serves HTTP to other machines. |
| `make reset-db` | Deletes `var/backend.db` and `var/warehouse.db` and reseeds them (demo users Alice and Bob, the deterministic warehouse). |

A typical local session:

```
make reset-db              # first run, or to start again from clean data
make backend               # logs one "plugin vdagent_<name> loaded: <name>" line per agent
cd frontend && npm install && npm run dev   # another terminal → http://localhost:5173
```

Changing a plugin's code or `.env` takes effect when the backend restarts.

Stop the backend before `make reset-db`: it deletes the SQLite files, and a running backend would
keep writing to the deleted ones. The database paths can be overridden
(`make reset-db BACKEND_DB=/tmp/b.db WAREHOUSE_DB=/tmp/w.db`); start the backend with the matching
`VDAGENT_BACKEND_DB` / `VDAGENT_WAREHOUSE_DB` to use them.

## Docker

```
docker compose up --build
```

Then open http://localhost:8000. The backend service is configured by
`backend/config.compose.yaml` and runs the five agent plugins in-process. Each plugin's
`agents/<name>/.env` is mounted read-only into the container (the image never contains `.env`
files), so all five must exist before `docker compose up`.

## Tests

```
uv run pytest                      # backend + every plugin
uv run pytest agents/data          # one plugin
cd frontend && npm test            # frontend
```
