# Team 6 cAi

VDaAgent analytics workflow using the React frontend from `vde-agent-demo`, a Hono API, Pi Agent Core,
PostgreSQL-backed sessions and artifacts, and isolated Docker workspaces. Agent plugins and MCP tools
are loaded into separate registries; warehouse tools use a provider registry with a synthetic local
warehouse as the default. The default roster contains the orchestrator and five specialist agents.

Start with the [documentation index](docs/README.md), including the API, agent, MCP tool,
architecture, and team folder ownership guides. Install backend and frontend packages,
copy `.env.example` to `.env`, and set the model API key plus local database credentials before
starting the stack.

```sh
corepack pnpm install --frozen-lockfile
npm --prefix frontend ci
docker pull node:24-slim
docker compose up --build
```

The API container serves the frontend at `http://localhost:3000`. For hot reload, run
`npm --prefix frontend run dev -- --host 127.0.0.1` and open `http://localhost:5173`. PostgreSQL
persists Pi sessions, private memory, chat history, tasks, datasets, charts, and reports. Docker
workspace volumes remain isolated by space, user, and agent.
