"""Real-estate DW mock (D7): deterministic, 15 DW v3.1.0 tables, approved snapshot, versioned semantic_config."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from vdagent_backend.re_warehouse import TABLES, build, checksum

CONFIG_VERSION = "sc-1"


def _db(tmp_path: Path, name: str = "re.db") -> str:
    path = str(tmp_path / name)
    build(path)
    return path


def test_seed_twice_same_checksum(tmp_path: Path) -> None:
    first = _db(tmp_path, "a.db")
    second = _db(tmp_path, "b.db")
    assert checksum(first) == checksum(second)
    build(first)  # rebuilding in place starts from scratch
    assert checksum(first) == checksum(second)


def test_all_15_tables_exist(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert names == set(TABLES) and len(TABLES) == 15
        for table in TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
    conn.close()


def test_snapshot_manifest_has_approved_row(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT snapshot_id, snapshot_date_key, status, semantic_config_version FROM snapshot_manifest"
            " ORDER BY snapshot_date_key"
        ).fetchall()
        latest_approved = [r for r in rows if r[2] == "APPROVED"][-1]
        assert latest_approved[0] == "SNAP-2026-09-28" and latest_approved[3] == CONFIG_VERSION
        assert any(r[2] == "DRAFT" for r in rows)  # a newer unapproved load exists and must be ignored
        loaded = {r[0] for r in conn.execute("SELECT DISTINCT snapshot_date_key FROM fact_unit_inventory_snapshot")}
        assert loaded == {r[1] for r in rows}
    conn.close()


def test_semantic_config_has_version_and_thresholds(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        cfg = {
            k: (json.loads(v), s)
            for k, v, s in conn.execute(
                "SELECT config_key, config_value, status FROM semantic_config WHERE config_version = ?",
                (CONFIG_VERSION,),
            )
        }
    conn.close()
    assert cfg["overdue_threshold_days"] == (90, "APPROVED")
    assert cfg["peer_area_tolerance_pct"] == ("0.10", "APPROVED")
    assert cfg["max_key_insights"] == (5, "APPROVED")
    assert cfg["min_group_size"] == (5, "PENDING")
    assert cfg["freshness_error_hours"] == (72, "PENDING")
    assert len(cfg["allowed_cause_codes"][0]) == 8
    assert set(cfg["cause_action_mapping"][0]) == set(cfg["allowed_cause_codes"][0])
    assert "chắc chắn do" in cfg["forbidden_phrases"][0]
    assert set(cfg["insight_templates"][0]) == set(cfg["allowed_cause_codes"][0])


def test_no_float_money_columns_text_decimal(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        for table in TABLES:
            for column in [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]:
                reals = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE typeof({column}) = 'real'").fetchone()[0]
                assert reals == 0, f"{table}.{column} holds floats"
    conn.close()


def _seeder():  # data/seed_re_warehouse.py, loaded as a module
    import importlib.util

    spec = importlib.util.spec_from_file_location("seed_re_warehouse_script",
                                                  Path(__file__).resolve().parents[2] / "data" / "seed_re_warehouse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _configured(module, monkeypatch, value: str) -> None:  # noqa: ANN001
    from dataclasses import replace

    from vdagent_backend.config import Config

    cfg = Config(backend_db="b.db", warehouse_db="w.db", mcp_public_url="http://m/mcp", frontend_dist="d",
                 re_warehouse_db=value)
    monkeypatch.setattr(module, "load_config", lambda: replace(cfg))


def test_the_seeder_never_writes_to_a_configured_real_warehouse(tmp_path: Path, monkeypatch, capsys) -> None:
    seeder = _seeder()
    monkeypatch.chdir(tmp_path)
    _configured(seeder, monkeypatch, "postgresql://reader:pg-s3cret@cdw.example.org:5432/cdw")
    assert seeder.main(["seed_re_warehouse.py"]) != 0
    out = capsys.readouterr()
    assert "postgresql" in (out.out + out.err) and "pg-s3cret" not in (out.out + out.err)
    assert list(tmp_path.iterdir()) == []  # no SQLite file named after the DSN, no var/


def test_the_seeder_builds_the_mock_at_its_explicit_default_when_nothing_is_configured(tmp_path: Path, monkeypatch) -> None:
    seeder = _seeder()
    monkeypatch.chdir(tmp_path)
    _configured(seeder, monkeypatch, "")
    assert seeder.main(["seed_re_warehouse.py"]) == 0
    assert (tmp_path / "var" / "re_warehouse.db").is_file()


def test_the_seeder_builds_the_mock_at_a_given_path(tmp_path: Path) -> None:
    assert _seeder().main(["seed_re_warehouse.py", str(tmp_path / "x.db")]) == 0
    assert (tmp_path / "x.db").is_file()
