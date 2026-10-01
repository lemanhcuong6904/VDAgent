"""`docker/check_warehouse.py`: before the Backend starts, `make up` proves from inside Docker that the real warehouse is
configured, reachable and holds the pinned APPROVED snapshot. It fails with a clear message, never with a credential."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location("check_warehouse", Path(__file__).resolve().parents[2] / "docker" / "check_warehouse.py")
assert SPEC and SPEC.loader
check_warehouse = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_warehouse)

DSN = "postgresql://vdagent_reader:s3cret-pw@host.docker.internal:5433/cdw"
ENV = {"VDAGENT_RE_WAREHOUSE_DB": DSN, "ORCH_SNAPSHOT_ID": "SNAP-20260630-01", "ORCH_SEMANTIC_VERSION": "3.1.0"}
MANIFEST = [("SNAP-20260630-01", "APPROVED", "3.1.0")]


class FakeConn:
    def __init__(self, manifest: list[tuple[str, str, str]], units: int = 47713) -> None:
        self.manifest, self.units = manifest, units

    def execute(self, sql: str) -> FakeConn:
        self._rows: list[tuple[Any, ...]] = self.manifest if "snapshot_manifest" in sql else [(self.units,)]
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


def run(env: dict[str, str], conn: FakeConn | Exception | None = None) -> tuple[bool, str]:
    def connect(dsn: str) -> FakeConn:
        assert dsn == env["VDAGENT_RE_WAREHOUSE_DB"]
        if isinstance(conn, Exception):
            raise conn
        return conn or FakeConn(MANIFEST)

    ok, lines = check_warehouse.check(env, connect)
    text = "\n".join(lines)
    assert "s3cret-pw" not in text  # never a credential
    return ok, text


def test_a_reachable_warehouse_with_the_pinned_snapshot_passes_and_says_what_it_is() -> None:
    ok, text = run(ENV)
    assert ok
    assert text.splitlines() == [
        "Warehouse backend: PostgreSQL",
        "Warehouse source: host.docker.internal:5433/cdw",
        "Snapshot: SNAP-20260630-01 (APPROVED)",
        "Semantic version: 3.1.0",
        "Units visible in schema re: 47713",
    ]


@pytest.mark.parametrize("dsn", ["", "./var/re_warehouse.db", "sqlite:///x.db"])
def test_no_postgres_dsn_is_a_hard_error_never_the_mock(dsn: str) -> None:
    ok, text = run({**ENV, "VDAGENT_RE_WAREHOUSE_DB": dsn})
    assert not ok and text.startswith("ERROR: Real warehouse is required. Set VDAGENT_RE_WAREHOUSE_DB in .env")


@pytest.mark.parametrize("key", ["ORCH_SNAPSHOT_ID", "ORCH_SEMANTIC_VERSION"])
def test_missing_pins_are_named(key: str) -> None:
    ok, text = run({**ENV, key: ""})
    assert not ok and f"Set {key} in .env" in text


def test_an_unreachable_warehouse_names_the_target_and_hints_at_docker_networking() -> None:
    ok, text = run(ENV, OSError(f"connection to {DSN} failed: Connection refused"))
    assert not ok and "cannot reach the warehouse at host.docker.internal:5433/cdw" in text
    assert "OSError" in text and "host.docker.internal" in text


def test_a_loopback_host_is_explained_because_inside_docker_it_is_the_container() -> None:
    ok, text = run({**ENV, "VDAGENT_RE_WAREHOUSE_DB": "postgresql://u:s3cret-pw@127.0.0.1:5433/cdw"}, OSError("refused"))
    assert not ok and "127.0.0.1 is the backend container itself" in text


def test_an_unknown_snapshot_lists_the_ones_the_warehouse_has() -> None:
    ok, text = run({**ENV, "ORCH_SNAPSHOT_ID": "SNAP-2026-09-28"})
    assert not ok and "SNAP-2026-09-28 is not in the warehouse" in text and "SNAP-20260630-01" in text


def test_a_snapshot_that_is_not_approved_is_refused() -> None:
    ok, text = run(ENV, FakeConn([("SNAP-20260630-01", "DRAFT", "3.1.0")]))
    assert not ok and "not APPROVED" in text


def test_a_semantic_version_that_does_not_match_the_snapshot_is_refused() -> None:
    ok, text = run({**ENV, "ORCH_SEMANTIC_VERSION": "sc-1"})
    assert not ok and "uses semantic version 3.1.0, not sc-1" in text


def test_an_empty_read_layer_is_refused() -> None:
    ok, text = run(ENV, FakeConn(MANIFEST, units=0))
    assert not ok and "no units" in text
