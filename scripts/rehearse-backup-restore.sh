#!/usr/bin/env bash
# M13.2 backup/restore rehearsal against a disposable PostgreSQL container.
#
#   PG_CONTAINER   container running postgres (default team6-test-db)
#   PG_NETWORK     docker network it is on (default team_6_cai_default)
#   PG_USER / PG_PASSWORD
#   OUT            directory for the dump and receipt (default ./.rehearsal)
#
# Creates two throwaway databases (source + restore), never touches any other.
set -euo pipefail

PG_CONTAINER=${PG_CONTAINER:-team6-test-db}
PG_NETWORK=${PG_NETWORK:-team_6_cai_default}
PG_USER=${PG_USER:-test}
PG_PASSWORD=${PG_PASSWORD:-testonly}
OUT=${OUT:-$(pwd)/.rehearsal}
STAMP=$(date +%s)
SOURCE=rehearsal_src_${STAMP}
TARGET=rehearsal_dst_${STAMP}
mkdir -p "$OUT"

psql() { docker exec "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -qAt -U "$PG_USER" -d postgres -c "$1"; }
node_run() {
  docker run --rm --network "$PG_NETWORK" --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$(pwd)":/app -v "$OUT":/out -w /app node:24-slim node_modules/.bin/tsx scripts/rehearse-backup-restore.ts "$@"
}
url() { echo "postgresql://${PG_USER}:${PG_PASSWORD}@${PG_CONTAINER}:5432/$1"; }
cleanup() { psql "DROP DATABASE IF EXISTS ${SOURCE}" || true; psql "DROP DATABASE IF EXISTS ${TARGET}" || true; }
trap cleanup EXIT

psql "CREATE DATABASE ${SOURCE}"
node_run seed "$(url "$SOURCE")" /out/state.json >/dev/null

t0=$(date +%s%N)
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$SOURCE" --format=custom --no-owner --file=/tmp/rehearsal.dump
docker cp "$PG_CONTAINER":/tmp/rehearsal.dump "$OUT/rehearsal.dump" >/dev/null
t1=$(date +%s%N)

psql "CREATE DATABASE ${TARGET}"
docker exec "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$TARGET" --no-owner --exit-on-error /tmp/rehearsal.dump
t2=$(date +%s%N)

# Negative control: REHEARSAL_CORRUPT=artifact flips one byte of one restored artifact,
# and the rehearsal must then FAIL. Proves the hash check reads bytes, not the hash column.
if [ "${REHEARSAL_CORRUPT:-}" = "artifact" ]; then
  docker exec "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -qAt -U "$PG_USER" -d "$TARGET" -c \
    "UPDATE artifact_contents SET content = set_byte(content, 0, (get_byte(content, 0) + 1) % 256)
     WHERE artifact_id = (SELECT artifact_id FROM artifact_contents ORDER BY artifact_id LIMIT 1)"
fi

set +e
node_run verify "$(url "$TARGET")" /out/state.json > "$OUT/verify.json"
status=$?
set -e

dump_sha=$(sha256sum "$OUT/rehearsal.dump" | cut -d' ' -f1)
dump_bytes=$(stat -c %s "$OUT/rehearsal.dump")
pg_version=$(docker exec "$PG_CONTAINER" pg_dump --version)
cat > "$OUT/receipt.json" <<JSON
{
  "milestone": "M13.2",
  "negative_control": "${REHEARSAL_CORRUPT:-none}",
  "kind": "backup-restore-rehearsal",
  "at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "tool": "${pg_version}",
  "dump": { "format": "custom", "sha256": "${dump_sha}", "bytes": ${dump_bytes} },
  "timings_ms": { "backup": $(( (t1 - t0) / 1000000 )), "restore": $(( (t2 - t1) / 1000000 )) },
  "verify": $(cat "$OUT/verify.json")
}
JSON
cat "$OUT/receipt.json"
exit $status
