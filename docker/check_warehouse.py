"""Preflight of `make up`, run inside Docker before the Backend starts (service `warehouse-check`): the real warehouse is
configured (`VDAGENT_RE_WAREHOUSE_DB=postgresql://…`), reachable from the container, and holds the pinned snapshot as
APPROVED with the pinned semantic version. Any failure stops `make up` with a clear message; there is no fallback to
the synthetic SQLite mock. Prints host, port and database only, never a user name or password.

Usage (in the image): python docker/check_warehouse.py
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

DSN_VAR = "VDAGENT_RE_WAREHOUSE_DB"
PINS = ("ORCH_SNAPSHOT_ID", "ORCH_SEMANTIC_VERSION")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def check(env: Mapping[str, str], connect: Callable[[str], Any]) -> tuple[bool, list[str]]:
    """`(ok, lines)`: the lines say what was checked, or what to fix."""
    dsn = (env.get(DSN_VAR) or "").strip()
    if not dsn.startswith(("postgresql://", "postgres://")):
        return False, [f"ERROR: Real warehouse is required. Set {DSN_VAR} in .env "
                       "(postgresql://<user>:<password>@<host>:<port>/<database>)."]
    missing = [key for key in PINS if not (env.get(key) or "").strip()]
    if missing:
        return False, [f"ERROR: Set {key} in .env (the warehouse snapshot to pin)." for key in missing]
    snapshot, semantic = env["ORCH_SNAPSHOT_ID"].strip(), env["ORCH_SEMANTIC_VERSION"].strip()
    url = urlsplit(dsn)
    target = f"{url.hostname}:{url.port or 5432}{url.path}"
    secret = url.password or ""

    try:
        conn = connect(dsn)
        manifest = conn.execute("SELECT snapshot_id, status, semantic_config_version FROM re.snapshot_manifest").fetchall()
        units = conn.execute("SELECT count(*) FROM re.dim_unit_master").fetchall()[0][0]
    except Exception as exc:  # report any driver error by class and first line, without the password
        detail = str(exc).splitlines()[0] if str(exc) else ""
        lines = [f"ERROR: cannot reach the warehouse at {target} ({type(exc).__name__}: {_redact(detail, dsn, secret)})."]
        if url.hostname in LOOPBACK:
            lines.append(f"  {url.hostname} is the backend container itself. For a PostgreSQL on this machine use "
                         "host.docker.internal and publish its port on the Docker bridge (see README).")
        else:
            lines.append("  Check host, port, database and password in .env; a PostgreSQL on this machine is "
                         "host.docker.internal and must accept connections from Docker containers.")
        return False, lines

    found = {row[0]: row for row in manifest}
    if snapshot not in found:
        return False, [f"ERROR: snapshot {snapshot} is not in the warehouse; it has: {', '.join(sorted(found)) or 'none'}. "
                       "Set ORCH_SNAPSHOT_ID in .env."]
    _, status, version = found[snapshot]
    if status != "APPROVED":
        return False, [f"ERROR: snapshot {snapshot} is {status}, not APPROVED; analyses only run on approved snapshots."]
    if version != semantic:
        return False, [f"ERROR: snapshot {snapshot} uses semantic version {version}, not {semantic}. "
                       "Set ORCH_SEMANTIC_VERSION in .env."]
    if not units:
        return False, [f"ERROR: the warehouse at {target} shows no units in schema re (apply docker/warehouse/apply-views.sh)."]
    return True, ["Warehouse backend: PostgreSQL", f"Warehouse source: {target}", f"Snapshot: {snapshot} (APPROVED)",
                  f"Semantic version: {semantic}", f"Units visible in schema re: {units}"]


def _redact(text: str, dsn: str, secret: str) -> str:
    text = text.replace(dsn, "<dsn>")
    return text.replace(secret, "***") if secret else text


def _connect(dsn: str) -> Any:
    import psycopg  # noqa: PLC0415  (only inside the image)

    return psycopg.connect(dsn, autocommit=True, connect_timeout=5)


def main() -> int:
    ok, lines = check(os.environ, _connect)
    print("\n".join(lines), file=sys.stdout if ok else sys.stderr, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
