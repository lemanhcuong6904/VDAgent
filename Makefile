# Local development. See README.md ("Makefile usage").

HOST         ?= 127.0.0.1
BACKEND_DB   ?= var/backend.db
WAREHOUSE_DB ?= var/warehouse.db

.DEFAULT_GOAL := help
.PHONY: help backend reset-db docker-env docker-build docker-up docker-down docker-test docker-offline-up docker-offline-down docker-offline-clean docker-live-up docker-live-check docker-live-logs docker-live-down docker-live-clean

help:
	@echo "make backend        start the backend on $(HOST):8000 with the agent plugins listed in backend/config.yaml"
	@echo "                    (each configured by agents/<name>/.env); HOST=0.0.0.0 serves other machines"
	@echo "make reset-db       delete and reseed $(BACKEND_DB) and $(WAREHOUSE_DB) (stop the backend first)"
	@echo "make docker-env     create missing agents/<name>/.env from .env.example (never overwrites)"
	@echo "make docker-build   build the runtime and test images"
	@echo "make docker-up      start backend on :8000 with ./var (seeds only missing databases)"
	@echo "make docker-down    stop the development stack (keeps ./var)"
	@echo "make docker-test    run the offline test suite in a container without network"
	@echo "make docker-offline-up / -down / -clean   isolated keyless backend on :8001 (named volume; -clean deletes it)"
	@echo "make docker-live-up / -check / -logs / -down / -clean   live-AI demo backend on :8022 (ORCH_LLM=on, agent .env keys)"

backend:
	uv run uvicorn vdagent_backend.app:app --host $(HOST) --port 8000

reset-db:
	rm -f $(BACKEND_DB) $(BACKEND_DB)-wal $(BACKEND_DB)-shm $(WAREHOUSE_DB) $(WAREHOUSE_DB)-wal $(WAREHOUSE_DB)-shm
	uv run python data/seed_warehouse.py $(WAREHOUSE_DB)
	uv run python data/seed_users.py $(BACKEND_DB)

AGENTS_WITH_ENV := orchestrator data compare insight report chart

docker-env:
	@for a in $(AGENTS_WITH_ENV); do \
		if [ -e agents/$$a/.env ]; then echo "kept    agents/$$a/.env"; \
		else cp agents/$$a/.env.example agents/$$a/.env && echo "created agents/$$a/.env (fill in the keys)"; fi; \
	done

docker-build:
	docker compose build
	docker compose --profile test build tests

docker-up:
	docker compose up -d backend

docker-down:
	docker compose down

docker-test:
	docker compose --profile test run --rm tests

docker-offline-up:
	docker compose --profile offline up -d backend-offline

docker-offline-down:
	docker compose --profile offline stop backend-offline seed-offline

docker-offline-clean:
	docker compose --profile offline rm -sf backend-offline seed-offline
	docker volume rm -f vdagent_offline_var

LIVE := docker compose --profile live
LIVE_URL := http://localhost:8022

docker-live-up:
	$(LIVE) up -d --build backend-live
	@for i in $$(seq 120); do [ "$$(docker inspect -f '{{.State.Health.Status}}' $$($(LIVE) ps -q backend-live))" = healthy ] && break; sleep 1; done
	@$(MAKE) --no-print-directory docker-live-check

# Non-secret status of the running live container (never prints keys).
docker-live-check:
	@echo "backend:   $(LIVE_URL)"
	@for v in ORCH_LLM ORCH_SNAPSHOT_ID ORCH_SEMANTIC_VERSION ORCH_DAG_TIMEOUT_S; do \
		printf '%-22s %s\n' "$$v" "$$($(LIVE) exec -T backend-live printenv $$v)"; done
	@printf '%-22s %s\n' health "$$(docker inspect -f '{{.State.Health.Status}}' $$($(LIVE) ps -q backend-live))"
	@printf '%-22s %s\n' agents "$$(curl -fsS -H 'X-User-Id: u_000000000001' $(LIVE_URL)/api/agents | python3 -c 'import json,sys; print(" ".join(a["name"] for a in json.load(sys.stdin)))')"
	@$(LIVE) logs backend-live | grep -E "orchestrator: |insight: data source" | tail -2 | sed -E 's/^.*INFO [^:]+: //'

docker-live-logs:
	$(LIVE) logs -f backend-live

docker-live-down:
	$(LIVE) stop backend-live seed-live

docker-live-clean:
	$(LIVE) rm -sf backend-live seed-live
	docker volume rm -f vdagent_live_var
