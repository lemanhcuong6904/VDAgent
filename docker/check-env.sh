#!/usr/bin/env bash
# Preflight for the LLM-mode Docker stacks: every mounted agents/<name>/.env exists and the keys each plugin needs to
# load are set. Prints file and variable NAMES only — never values. Usage: docker/check-env.sh [repo-root]
set -u
ROOT=${1:-$(cd "$(dirname "$0")/.." && pwd)}
AGENTS="orchestrator data insight compare chart report"
LLM_REQUIRED="orchestrator data report"          # these plugins do not load without an OpenAI-compatible endpoint
REQUIRED_KEYS="OPENAI_API_KEY OPENAI_BASE_URL LLM_MODEL"
problems=0

value_set() {  # file key → 0 when `key=<non-empty>` is present (comments and quotes ignored)
  grep -Eq "^[[:space:]]*$2[[:space:]]*=[[:space:]]*['\"]?[^[:space:]'\"#]" "$1"
}

for agent in $AGENTS; do
  file="$ROOT/agents/$agent/.env"
  if [ ! -f "$file" ]; then
    echo "MISSING agents/$agent/.env  → run: make docker-env   (then fill in the keys)"
    problems=1
  fi
done
for agent in $LLM_REQUIRED; do
  file="$ROOT/agents/$agent/.env"
  [ -f "$file" ] || continue
  for key in $REQUIRED_KEYS; do
    value_set "$file" "$key" || { echo "EMPTY   agents/$agent/.env: $key"; problems=1; }
  done
done
insight="$ROOT/agents/insight/.env"
if [ -f "$insight" ] && ! value_set "$insight" OPENAI_API_KEY && ! value_set "$insight" GEMINI_API_KEY; then
  echo "WARN    agents/insight/.env: no OPENAI_API_KEY / GEMINI_API_KEY → Insight uses template wording (no LLM)"
fi
if [ "$problems" -ne 0 ]; then
  echo "Fix the lines above, then run the command again."
  exit 1
fi
echo "OK      agent .env files present; LLM keys set for orchestrator, data, report"
