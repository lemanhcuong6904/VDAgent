"""Build the real-estate DW mock (`var/re_warehouse.db`, D7) deterministically.

Usage: uv run python data/seed_re_warehouse.py [PATH]
PATH defaults to `re_warehouse_db` from the backend config (`VDAGENT_RE_WAREHOUSE_DB` / `VDAGENT_CONFIG` honoured).
The database is rebuilt from scratch on every run; the printed checksum is stable across runs.
"""

from __future__ import annotations

import sys

from vdagent_backend.config import load_config
from vdagent_backend.re_warehouse import LATEST_APPROVED, build


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else load_config().re_warehouse_db
    digest = build(path)
    print(f"re warehouse: {path}  latest approved snapshot: {LATEST_APPROVED}  checksum: {digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
