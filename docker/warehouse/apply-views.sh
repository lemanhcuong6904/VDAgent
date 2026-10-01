#!/bin/sh
# Applies the canonical read layer (schema `re`) over the DATA team's warehouse (schema `gold`) and creates the
# read-only role the Backend connects as. Idempotent. The warehouse itself is restored from warehouse/backup first.
#
# Env: PG* (libpq: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE) for an admin connection;
#      VDAGENT_READER_PASSWORD (required, never committed) for the role `vdagent_reader`.
# Needs `psql` and this directory; in a container mount the repo's docker/warehouse folder, e.g.
#   docker run --rm --network host -v "$PWD/docker/warehouse:/w:ro" -e PGHOST=localhost -e PGPORT=5433 -e PGUSER=postgres \n#     -e PGPASSWORD=... -e PGDATABASE=cdw -e VDAGENT_READER_PASSWORD=... postgres:16 sh /w/apply-views.sh
set -eu

: "${VDAGENT_READER_PASSWORD:?set VDAGENT_READER_PASSWORD (the password of the read-only role vdagent_reader)}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$(psql -tAc "SELECT to_regnamespace('gold')")" ]; then
  echo "apply-views: schema gold is missing; restore warehouse/backup/*.dump first" >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 -v pw="$VDAGENT_READER_PASSWORD" -q <<'SQL'
SELECT NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vdagent_reader') AS missing \gset
\if :missing
  CREATE ROLE vdagent_reader LOGIN;
\endif
ALTER ROLE vdagent_reader PASSWORD :'pw';
SQL
psql -v ON_ERROR_STOP=1 -q -f "$HERE/canonical_views.sql"
echo "apply-views: done ($(psql -tAc 'SELECT count(*) FROM re.dim_unit_master') units visible in schema re)"
