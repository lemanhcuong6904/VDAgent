#!/usr/bin/env bash
# Preflight for `make up`: the root .env exists, sets the LLM keys the plugins need to load (Orchestrator, Data and
# Report do not load without an OpenAI-compatible endpoint) and points at the real PostgreSQL warehouse with its snapshot
# pins. Prints file and variable NAMES only — never values. Reachability and the snapshot are then checked from inside
# Docker (docker/check_warehouse.py). Usage: docker/check-env.sh [repo-root]
set -u
ROOT=${1:-$(cd "$(dirname "$0")/.." && pwd)}
FILE="$ROOT/.env"
REQUIRED_KEYS="OPENAI_API_KEY OPENAI_BASE_URL LLM_MODEL VDAGENT_RE_WAREHOUSE_DB ORCH_SNAPSHOT_ID ORCH_SEMANTIC_VERSION"

if [ ! -f "$FILE" ]; then
  echo "MISSING .env  → run: cp .env.example .env   (then fill in $REQUIRED_KEYS)"
  exit 1
fi

value_of() {  # key → its value (last assignment wins, surrounding quotes removed); never printed
  grep -E "^[[:space:]]*$1[[:space:]]*=" "$FILE" | tail -1 | sed -E "s/^[^=]*=[[:space:]]*//; s/[[:space:]]+#.*$//; s/^['\"]//; s/['\"]$//"
}

problems=0
for key in $REQUIRED_KEYS; do
  [ -n "$(value_of "$key")" ] || { echo "EMPTY   .env: $key"; problems=1; }
done
dsn=$(value_of VDAGENT_RE_WAREHOUSE_DB)
if [ -z "$dsn" ]; then
  echo "ERROR: Real warehouse is required. Set VDAGENT_RE_WAREHOUSE_DB in .env."
elif ! printf '%s' "$dsn" | grep -Eq '^postgres(ql)?://'; then
  echo "ERROR: VDAGENT_RE_WAREHOUSE_DB must be a postgresql://… DSN of the real warehouse (the SQLite mock runs only with make mock-up)."
  problems=1
elif printf '%s' "$dsn" | grep -Eq '@(127\.0\.0\.1|localhost|\[::1\])[:/]'; then
  echo "ERROR: VDAGENT_RE_WAREHOUSE_DB points at 127.0.0.1/localhost, which inside Docker is the backend container itself."
  echo "       For a PostgreSQL on this machine use host.docker.internal (see README)."
  problems=1
fi
if [ "$problems" -ne 0 ]; then
  echo "Fill in the variables above in .env, then run make up again."
  exit 1
fi
echo "OK      .env sets $REQUIRED_KEYS"
