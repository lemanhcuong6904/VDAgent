# Local development. Start the product with `make up` (README.md "Quick Start").

HOST         ?= 127.0.0.1
BACKEND_DB   ?= var/backend.db
WAREHOUSE_DB ?= var/warehouse.db
DOCS_MODULES := vdagent_sdk vdagent_backend.mcp.reference

.DEFAULT_GOAL := help
.PHONY: help up down restart logs status build warehouse-check mock-up mock-down backend reset-db sdk-docs sdk-docs-serve docker-test

# Always this project's compose file: a bare `docker compose` would also merge any docker-compose.override.yml.
COMPOSE := docker compose -f docker-compose.yml
AGENTS  := orchestrator data compare insight report chart

help:
	@echo "make up       build and start the product against the real warehouse (UI + API on http://localhost:8000;"
	@echo "              needs .env, see .env.example)"
	@echo "make down     stop it (app data is kept in the Docker volume vdagent_real_var)"
	@echo "make logs     follow the backend log"
	@echo "make status   show product container status and health"
	@echo "make restart  stop and start the product"
	@echo "make build    build the product image without starting it"
	@echo "make warehouse-check  validate the real warehouse from inside Docker"
	@echo ""
	@echo "make mock-up / mock-down   synthetic mock warehouse, no keys, on :8001 (tests and offline development only)"
	@echo "make docker-test           run the offline test suite in a container without network"
	@echo "make backend        run the backend on the host ($(HOST):8000; plugins configured by agents/<name>/.env)"
	@echo "make reset-db       delete and reseed $(BACKEND_DB) and $(WAREHOUSE_DB) for make backend (stop it first)"
	@echo "make sdk-docs       build the agent developer reference (SDK + MCP tools) into docs/sdk/"
	@echo "make sdk-docs-serve serve the same reference on $(HOST):8080, rebuilt when a docstring changes"

up:
	@bash docker/check-env.sh
	@$(COMPOSE) up -d --build --wait backend || { $(COMPOSE) logs --no-log-prefix warehouse-check; exit 1; }
	@$(COMPOSE) logs --no-log-prefix warehouse-check
	@$(COMPOSE) exec -T backend python -c "import json,sys,urllib.request; \
	r=urllib.request.Request('http://127.0.0.1:8000/api/agents', headers={'X-User-Id': 'u_000000000001'}); \
	got={a['name'] for a in json.load(urllib.request.urlopen(r))}; missing=set('$(AGENTS)'.split())-got; \
	print('agents loaded:', ' '.join(sorted(got))); \
	missing and sys.exit('MISSING agents: ' + ' '.join(sorted(missing)) + ' -> see: make logs | grep failed')"
	@echo "VDaAgent is up: http://localhost:$$($(COMPOSE) port backend 8000 | sed 's/.*://')  (UI and API)"

down:
	$(COMPOSE) down

restart:
	$(MAKE) down
	$(MAKE) up

status:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

warehouse-check:
	@bash docker/check-env.sh
	$(COMPOSE) run --rm warehouse-check

logs:
	$(COMPOSE) logs -f backend

# The synthetic mock warehouse, explicitly (keyless, deterministic; never the product path).
mock-up:
	$(COMPOSE) --profile offline up -d --build --wait backend-offline
	@echo "MOCK warehouse (synthetic data) on http://localhost:8001"

mock-down:
	$(COMPOSE) --profile offline rm -sf backend-offline seed-offline

backend:
	uv run uvicorn vdagent_backend.app:app --host $(HOST) --port 8000

reset-db:
	rm -f $(BACKEND_DB) $(BACKEND_DB)-wal $(BACKEND_DB)-shm $(WAREHOUSE_DB) $(WAREHOUSE_DB)-wal $(WAREHOUSE_DB)-shm
	uv run python data/seed_warehouse.py $(WAREHOUSE_DB)
	uv run python data/seed_users.py $(BACKEND_DB)

docker-test:
	$(COMPOSE) --profile test run --build --rm tests

sdk-docs:
	uv run pdoc $(DOCS_MODULES) -o docs/sdk

sdk-docs-serve:
	uv run pdoc $(DOCS_MODULES) -h $(HOST) -p 8080 -n
