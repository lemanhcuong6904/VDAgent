"""The real-estate DW is chosen explicitly and never silently: no DSN, a malformed DSN or an unknown scheme stops the
Backend at startup; a plain path is the synthetic SQLite mock (tests, `make mock-up`) and only when named; an
unreachable PostgreSQL warehouse fails the query and is never replaced by the mock."""

from __future__ import annotations

from pathlib import Path

import pytest

from vdagent_backend.app import create_app
from vdagent_backend.config import Config, load_config
from vdagent_backend.warehouse import RealEstateWarehouse, ReWarehouseConfigError, SqlError
from vdagent_contracts.scope import AuthorizedScope

REPO = Path(__file__).resolve().parents[3]
SECRET = "pg-s3cret"


@pytest.mark.parametrize("value", ["", "   "])
def test_no_warehouse_configured_fails_fast_and_names_the_variable(value: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ReWarehouseConfigError, match="VDAGENT_RE_WAREHOUSE_DB"):
        RealEstateWarehouse(value)
    assert not (tmp_path / "var").exists()  # nothing silently opened or created


@pytest.mark.parametrize("dsn", [
    "postgresql://",                                              # nothing at all
    f"postgresql://reader:{SECRET}@/cdw",                         # no host
    f"postgresql://reader:{SECRET}@db.example.org:5432",          # no database
    f"postgresql://reader:{SECRET}@db.example.org:5432/",         # empty database
    f"postgressql://reader:{SECRET}@db.example.org:5432/cdw",     # typo in the scheme: never a SQLite file name
    f"mysql://reader:{SECRET}@db.example.org:3306/cdw",           # another database
])
def test_a_malformed_dsn_fails_fast_without_leaking_the_password(dsn: str) -> None:
    with pytest.raises(ReWarehouseConfigError, match="VDAGENT_RE_WAREHOUSE_DB") as exc:
        RealEstateWarehouse(dsn)
    assert SECRET not in str(exc.value)


def test_a_postgresql_dsn_selects_postgresql_without_connecting() -> None:
    wh = RealEstateWarehouse(f"postgresql://reader:{SECRET}@cdw.abc.ap-southeast-1.rds.amazonaws.com:5432/cdw?sslmode=require")
    assert wh.source == {"backend": "postgresql", "host": "cdw.abc.ap-southeast-1.rds.amazonaws.com", "port": 5432,
                         "database": "cdw"}


def test_an_explicit_path_selects_the_sqlite_mock(tmp_path: Path) -> None:
    assert RealEstateWarehouse(str(tmp_path / "re_warehouse.db")).source == {"backend": "sqlite", "file": "re_warehouse.db"}


async def test_an_unreachable_postgresql_warehouse_fails_and_never_falls_back_to_the_mock(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    wh = RealEstateWarehouse(f"postgresql://reader:{SECRET}@127.0.0.1:1/cdw", timeout_s=2)
    with pytest.raises(SqlError, match="warehouse unavailable") as exc:
        await wh.query("SELECT count(*) FROM dim_unit_master", AuthorizedScope(project_ids=["100"]))
    assert SECRET not in str(exc.value)
    assert wh.source["backend"] == "postgresql" and not (tmp_path / "var").exists()


def _cfg(tmp_path: Path, **values: str) -> Config:
    return Config(backend_db=str(tmp_path / "backend.db"), warehouse_db=str(tmp_path / "warehouse.db"),
                  mcp_public_url="http://mcp.test/mcp", frontend_dist=str(tmp_path / "no-dist"), **values)


def test_the_backend_does_not_start_without_a_warehouse(tmp_path: Path) -> None:
    with pytest.raises(ReWarehouseConfigError, match="VDAGENT_RE_WAREHOUSE_DB"):
        create_app(_cfg(tmp_path))


def test_the_backend_does_not_start_with_a_malformed_dsn(tmp_path: Path) -> None:
    with pytest.raises(ReWarehouseConfigError):
        create_app(_cfg(tmp_path, re_warehouse_db="postgres://reader@/cdw"))


def test_the_backend_starts_on_an_explicit_mock(tmp_path: Path) -> None:
    assert create_app(_cfg(tmp_path, re_warehouse_db=str(tmp_path / "re_warehouse.db"))) is not None


@pytest.mark.parametrize("name", ["config.yaml", "config.compose.yaml"])
def test_no_backend_config_names_the_mock_implicitly(name: str, monkeypatch) -> None:
    monkeypatch.delenv("VDAGENT_RE_WAREHOUSE_DB", raising=False)
    monkeypatch.setattr("vdagent_backend.config._load_env_file", lambda _path: None)  # the developer's .env stays out
    assert load_config(REPO / "backend" / name).re_warehouse_db == ""
