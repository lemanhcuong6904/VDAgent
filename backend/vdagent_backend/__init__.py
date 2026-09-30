"""vdagent Backend: REST/SSE API, invocation runtime and MCP server for in-process agent plugins.

Package map:

- `app`: composition root (`create_app`, lazy `app` for uvicorn).
- `config`: `config.yaml` + `VDAGENT_*` overrides (`Config`, `PluginSpec`, `load_config`).
- `core`: ids, clock, error helpers, the SSE `EventBus`, MCP tokens.
- `persistence`: database engine, table metadata, dialect types, query helpers, Alembic migrations.
- `plugins`: plugin loading and the immutable `AgentRegistry` (with MCP grants).
- `conversations`: users, tasks, invocations and message stacks, with their API shapes.
- `artifacts`: datasets, charts and reports (`ArtifactService`).
- `warehouse`: read-only SQL over the warehouse and over datasets.
- `memory`: agent memory (`ScopedMemory`) and its dialect-specific search.
- `runtime`: scheduling, agent turns, agent calls (`Engine`).
- `http`: REST routers, SSE, the frontend mount.
- `mcp`: the MCP server, tool catalog and handlers.

Dependency rule (enforced by `tests/test_architecture.py`): `core` imports nothing of the Backend;
`config` only `core`; domains (`conversations`, `artifacts`, `memory`, `warehouse`) never import
`http`, `mcp` or `runtime`; `http` and `mcp` never import each other; only `app` imports everything.
Across packages, code imports only the names a package exports in `__all__`.
"""
