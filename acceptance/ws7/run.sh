#!/usr/bin/env bash
# WS7 acceptance (F-06): fresh isolated offline stack -> golden request -> browser -> store audit -> kill/restart.
# Only resources of project $WS7_PROJECT (default vdagent_ws7acc) and volume vdagent_ws7acc_var are created and removed.
#   WS7_PORT (8021)  WS7_OUT (acceptance/ws7/out)  WS7_KEEP=1 keeps the stack  WS7_BROWSER_PYTHON (python with playwright)
set -euo pipefail
cd "$(dirname "$0")/../.."
P=${WS7_PROJECT:-vdagent_ws7acc}
export WS7_PORT=${WS7_PORT:-8021}
export WS7_BASE_URL="http://localhost:${WS7_PORT}"
export WS7_OUT=${WS7_OUT:-acceptance/ws7/out}
mkdir -p "$WS7_OUT"
DC=(docker compose -p "$P" -f docker-compose.yml -f acceptance/ws7/compose.ws7.yml --profile offline)
PYTEST=(uv run pytest -q -p no:cacheprovider --rootdir acceptance/ws7 -c /dev/null)

cleanup() { [[ "${WS7_KEEP:-}" == 1 ]] || { "${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; docker volume rm -f vdagent_ws7acc_var >/dev/null 2>&1 || true; }; }
trap cleanup EXIT

wait_up() { for _ in $(seq 120); do curl -fsS -H 'X-User-Id: u_000000000001' "$WS7_BASE_URL/api/agents" >/dev/null 2>&1 && return 0; sleep 1; done; echo "backend did not start" >&2; return 1; }
snapshot_db() {  # a consistent copy of the live SQLite store (WAL included) for the store-level checks
  "${DC[@]}" exec -T backend-offline python -c "import sqlite3; s=sqlite3.connect('/app/var/backend.db'); d=sqlite3.connect('/tmp/ws7.db'); s.backup(d); d.close()"
  "${DC[@]}" cp backend-offline:/tmp/ws7.db "$WS7_OUT/backend.db" >/dev/null
  export WS7_DB="$WS7_OUT/backend.db"
}

cleanup  # start from nothing: a fresh volume every run
"${DC[@]}" build backend-offline
"${DC[@]}" up -d backend-offline
wait_up

echo "== 1. golden request over REST"
"${PYTEST[@]}" acceptance/ws7/test_api_golden.py
echo "== 2. real browser"
${WS7_BROWSER_PYTHON:-uv run python} -m pytest -q -p no:cacheprovider --rootdir acceptance/ws7 -c /dev/null acceptance/ws7/test_browser.py
echo "== 3. store: hashes, lineage, evidence"
snapshot_db
"${PYTEST[@]}" acceptance/ws7/test_lineage.py
echo "== 4. kill -9 mid-run, restart"
body=$(printf '{"content": "%s"}' "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.")
export WS7_KILLED_TASK=$(curl -fsS -X POST -H 'X-User-Id: u_000000000001' -H 'Content-Type: application/json' \
  -H "Idempotency-Key: ws7-kill-$(date +%s%N)" -d "$body" "$WS7_BASE_URL/api/agents/orchestrator/messages" | python3 -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')
"${DC[@]}" kill -s KILL backend-offline
"${DC[@]}" up -d backend-offline
wait_up
snapshot_db
"${PYTEST[@]}" acceptance/ws7/test_restart.py
echo "WS7 acceptance: PASS (evidence in $WS7_OUT)"
