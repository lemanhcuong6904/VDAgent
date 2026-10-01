"""Build a read-only SQLite projection of the validated Smart City CSV pack.

PostgreSQL remains the 16-table contract authority. This file lets the current
Python backend's MCP SQL tools smoke-test the same synthetic data without
replacing its retail demo database.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "data-warehouse-data-contract-v3.1.0.md"
DEFAULT_PACK = ROOT / "data" / "mock" / "vhsc_20260630"
DEFAULT_DESTINATION = ROOT / "var" / "vhsc_warehouse.db"
TYPE_MAP = {
    "INTEGER": "INTEGER", "BIGINT": "INTEGER", "SMALLINT": "INTEGER",
    "DECIMAL": "REAL", "BOOLEAN": "INTEGER", "VARCHAR": "TEXT",
    "DATE": "TEXT", "JSONB": "TEXT", "TEXT": "TEXT",
}


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f'"{value}"'


def _contract_types() -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {}
    current = None
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^### \d+\. `([a-z_]+)`$", line)
        if heading:
            current = heading.group(1)
            tables[current] = {}
            continue
        column = re.match(r"^\| ([a-z][a-z0-9_]*) \| (VARCHAR|DECIMAL|INTEGER|BIGINT|SMALLINT|DATE|BOOLEAN|JSONB|TEXT)", line)
        if column and current:
            tables[current][column.group(1)] = column.group(2)
    if len(tables) != 16:
        raise ValueError("Expected 16 warehouse tables in the data contract")
    return tables


def _value(raw: str, kind: str):
    if raw == "":
        return None
    if kind == "BOOLEAN":
        if raw not in {"t", "f"}:
            raise ValueError(f"Invalid CSV boolean: {raw!r}")
        return 1 if raw == "t" else 0
    if kind in {"INTEGER", "BIGINT", "SMALLINT"}:
        return int(raw)
    if kind == "DECIMAL":
        return float(raw)
    return raw


def build_projection(pack_dir: Path, destination: Path) -> None:
    pack_dir = Path(pack_dir)
    destination = Path(destination)
    manifest = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    if manifest["project_key"] != 200 or manifest["project_id"] != "PRJ-VHSC":
        raise ValueError("Not a Smart City pack")
    contract = _contract_types()
    order = manifest["table_order"]
    if set(order) != set(contract) or len(order) != 16:
        raise ValueError("Pack table list does not match the 16-table contract")

    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix="vhsc_", suffix=".db", dir=destination.parent)
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        with closing(sqlite3.connect(temp_path)) as conn:
            for table in order:
                columns = contract[table]
                definitions = ", ".join(f"{_identifier(name)} {TYPE_MAP[kind]}" for name, kind in columns.items())
                conn.execute(f"CREATE TABLE {_identifier(table)} ({definitions})")
                with (pack_dir / f"{table}.csv").open(encoding="utf-8", newline="") as file:
                    reader = csv.DictReader(file)
                    if reader.fieldnames != list(columns):
                        raise ValueError(f"Column mismatch in {table}.csv")
                    placeholders = ", ".join("?" for _ in columns)
                    values = ([ _value(row[name], kind) for name, kind in columns.items() ] for row in reader)
                    conn.executemany(f"INSERT INTO {_identifier(table)} VALUES ({placeholders})", values)
                actual = conn.execute(f"SELECT COUNT(*) FROM {_identifier(table)}").fetchone()[0]
                if actual != manifest["row_counts"][table]:
                    raise ValueError(f"Row count mismatch in {table}: {actual}")
                for key in ("unit_key", "project_key", "snapshot_date_key"):
                    if key in columns:
                        conn.execute(f"CREATE INDEX {_identifier('ix_' + table + '_' + key)} "
                                     f"ON {_identifier(table)} ({_identifier(key)})")
            conn.commit()
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    build_projection(args.pack_dir, args.output)
    print(f"Smart City SQLite projection ready: {args.output}")


if __name__ == "__main__":
    main()
