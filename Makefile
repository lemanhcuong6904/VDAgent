# Local development. See README.md ("Makefile usage").

HOST         ?= 127.0.0.1
BACKEND_DB   ?= var/backend.db
WAREHOUSE_DB ?= var/warehouse.db
DOCS_MODULES := vdagent_sdk vdagent_backend.mcp.reference

.DEFAULT_GOAL := help
.PHONY: help backend reset-db sdk-docs sdk-docs-serve

help:
	@echo "make backend        start the backend on $(HOST):8000 with the agent plugins listed in backend/config.yaml"
	@echo "                    (each configured by agents/<name>/.env); HOST=0.0.0.0 serves other machines"
	@echo "make reset-db       delete and reseed $(BACKEND_DB) and $(WAREHOUSE_DB) (stop the backend first)"
	@echo "make sdk-docs       build the agent developer reference (SDK + MCP tools) into docs/sdk/"
	@echo "make sdk-docs-serve serve the same reference on $(HOST):8080, rebuilt when a docstring changes"

backend:
	uv run uvicorn vdagent_backend.app:app --host $(HOST) --port 8000

reset-db:
	rm -f $(BACKEND_DB) $(BACKEND_DB)-wal $(BACKEND_DB)-shm $(WAREHOUSE_DB) $(WAREHOUSE_DB)-wal $(WAREHOUSE_DB)-shm
	uv run python data/seed_warehouse.py $(WAREHOUSE_DB)
	uv run python data/seed_users.py $(BACKEND_DB)

sdk-docs:
	uv run pdoc $(DOCS_MODULES) -o docs/sdk

sdk-docs-serve:
	uv run pdoc $(DOCS_MODULES) -h $(HOST) -p 8080 -n
