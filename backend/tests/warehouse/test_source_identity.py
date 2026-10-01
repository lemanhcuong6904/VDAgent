"""The real-estate DW says what it is: which backend serves it and where, never with credentials. Agents derive their
source labels from this identity instead of trusting an independent setting."""

from __future__ import annotations

from vdagent_backend.warehouse import RealEstateWarehouse, startup_lines


def test_a_postgres_dsn_is_identified_without_its_credentials() -> None:
    source = RealEstateWarehouse("postgresql://vdagent_reader:s3cret@dw.example.org:6543/cdw").source
    assert source == {"backend": "postgresql", "host": "dw.example.org", "port": 6543, "database": "cdw"}
    assert "s3cret" not in repr(source) and "vdagent_reader" not in repr(source)


def test_the_default_postgres_port_is_filled_in() -> None:
    assert RealEstateWarehouse("postgres://u:p@host.docker.internal/cdw").source["port"] == 5432


def test_a_sqlite_file_is_identified_as_the_mock_by_its_file_name() -> None:
    assert RealEstateWarehouse("/app/var/re_warehouse.db").source == {"backend": "sqlite", "file": "re_warehouse.db"}


def test_the_startup_lines_name_the_backend_and_a_safe_source() -> None:
    pg = startup_lines(RealEstateWarehouse("postgresql://u:s3cret@dw:5432/cdw").source)
    assert pg == ["Warehouse backend: PostgreSQL", "Warehouse source: dw:5432/cdw"]
    assert startup_lines(RealEstateWarehouse("./var/re_warehouse.db").source) == [
        "Warehouse backend: SQLite (synthetic mock)", "Warehouse source: re_warehouse.db"]
