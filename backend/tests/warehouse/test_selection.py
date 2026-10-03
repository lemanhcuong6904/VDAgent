"""Which PostgreSQL warehouse the Backend reads (`VDAGENT_WAREHOUSE_MODE` = aws | local | auto).

`aws` reads the AWS RDS Central Data Warehouse only (remote host, SSL, schema `gold`) and never falls back; `local` reads
the local snapshot only (e.g. host.docker.internal:5433, no SSL); `auto` reads AWS and falls back to the local snapshot
only when AWS is unavailable. No error message ever carries a credential.
"""

from __future__ import annotations

import pytest

from vdagent_backend.warehouse.selection import (
    WarehouseConfigError,
    WarehouseTarget,
    choose,
    is_local_host,
    plan,
)

AWS = "postgresql://cdw_reader:aws-s3cret@cdw.abc123xyz.ap-southeast-1.rds.amazonaws.com:5432/cdw"
LOCAL = "postgresql://vdagent_reader:local-s3cret@host.docker.internal:5433/cdw"


def env(**over: str) -> dict[str, str]:
    return {"VDAGENT_RE_WAREHOUSE_DB": AWS, "VDAGENT_RE_WAREHOUSE_LOCAL_DB": LOCAL, **over}


def refused(values: dict[str, str]) -> str:
    with pytest.raises(WarehouseConfigError) as caught:
        plan(values)
    text = str(caught.value)
    assert "aws-s3cret" not in text and "local-s3cret" not in text  # never a credential
    return text


# ---- aws ------------------------------------------------------------------------------------------------------------


def test_aws_mode_reads_the_remote_dsn_over_ssl_in_schema_gold_and_never_falls_back() -> None:  # T1 (policy)
    p = plan(env(VDAGENT_WAREHOUSE_MODE="aws"))
    assert p.mode == "aws" and p.fallback is None
    t = p.primary
    assert (t.origin, t.host, t.port, t.database, t.schema, t.sslmode) == (
        "aws", "cdw.abc123xyz.ap-southeast-1.rds.amazonaws.com", 5432, "cdw", "gold", "require")
    assert "aws-s3cret" not in repr(t) and "aws-s3cret" not in t.describe()


def test_aws_mode_never_probes_and_never_falls_back() -> None:
    def unavailable(_: WarehouseTarget) -> str:
        raise AssertionError("aws mode must not probe for a fallback")

    target, notes = choose(plan(env(VDAGENT_WAREHOUSE_MODE="aws")), unavailable)
    assert target.origin == "aws" and notes == []


def test_aws_mode_with_a_local_dsn_is_refused() -> None:  # T3
    text = refused(env(VDAGENT_WAREHOUSE_MODE="aws", VDAGENT_RE_WAREHOUSE_DB=LOCAL))
    assert "VDAGENT_WAREHOUSE_MODE=aws" in text and "host.docker.internal" in text and "not a remote" in text


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer", "nonsense"])
def test_aws_mode_requires_ssl(sslmode: str) -> None:
    text = refused(env(VDAGENT_WAREHOUSE_MODE="aws", VDAGENT_RE_WAREHOUSE_SSLMODE=sslmode))
    assert "VDAGENT_RE_WAREHOUSE_SSLMODE" in text and "require" in text


def test_aws_mode_refuses_ssl_switched_off_inside_the_dsn() -> None:
    text = refused(env(VDAGENT_WAREHOUSE_MODE="aws", VDAGENT_RE_WAREHOUSE_DB=AWS + "?sslmode=disable"))
    assert "sslmode=disable" in text


@pytest.mark.parametrize("sslmode", ["require", "verify-ca", "verify-full"])
def test_aws_mode_accepts_the_secure_ssl_modes(sslmode: str) -> None:
    assert plan(env(VDAGENT_WAREHOUSE_MODE="aws", VDAGENT_RE_WAREHOUSE_SSLMODE=sslmode)).primary.sslmode == sslmode


def test_the_schema_is_configurable_but_only_to_a_known_read_layer() -> None:
    assert plan(env(VDAGENT_WAREHOUSE_MODE="aws", VDAGENT_RE_WAREHOUSE_SCHEMA="re")).primary.schema == "re"
    assert "VDAGENT_RE_WAREHOUSE_SCHEMA" in refused(env(VDAGENT_WAREHOUSE_MODE="aws", VDAGENT_RE_WAREHOUSE_SCHEMA="public"))


# ---- local ----------------------------------------------------------------------------------------------------------


def test_local_mode_reads_the_local_snapshot_without_ssl() -> None:  # T2 (policy)
    p = plan(env(VDAGENT_WAREHOUSE_MODE="local"))
    t = p.primary
    assert p.mode == "local" and p.fallback is None
    assert (t.origin, t.host, t.port, t.database, t.schema, t.sslmode) == ("local", "host.docker.internal", 5433, "cdw", "re", None)


def test_local_mode_uses_the_active_dsn_when_no_separate_local_dsn_is_set() -> None:
    p = plan({"VDAGENT_WAREHOUSE_MODE": "local", "VDAGENT_RE_WAREHOUSE_DB": LOCAL})
    assert p.primary.host == "host.docker.internal"


def test_an_unset_mode_is_local_so_an_existing_local_setup_keeps_working() -> None:
    assert plan({"VDAGENT_RE_WAREHOUSE_DB": LOCAL}).mode == "local"


def test_local_mode_with_an_aws_dsn_is_refused() -> None:  # T4
    text = refused({"VDAGENT_WAREHOUSE_MODE": "local", "VDAGENT_RE_WAREHOUSE_DB": AWS})
    assert "VDAGENT_WAREHOUSE_MODE=local" in text and "rds.amazonaws.com" in text and "VDAGENT_RE_WAREHOUSE_LOCAL_DB" in text


def test_local_mode_with_an_aws_local_dsn_is_refused_too() -> None:
    assert "VDAGENT_RE_WAREHOUSE_LOCAL_DB" in refused(env(VDAGENT_WAREHOUSE_MODE="local", VDAGENT_RE_WAREHOUSE_LOCAL_DB=AWS))


# ---- auto -----------------------------------------------------------------------------------------------------------


def test_auto_mode_uses_aws_when_it_is_available() -> None:  # T5
    probed: list[str] = []

    def unavailable(t: WarehouseTarget) -> str | None:
        probed.append(t.origin)
        return None

    target, notes = choose(plan(env(VDAGENT_WAREHOUSE_MODE="auto")), unavailable)
    assert target.origin == "aws" and probed == ["aws"]
    assert notes == ["auto: AWS warehouse available"]


def test_auto_mode_falls_back_to_the_local_snapshot_only_when_aws_is_unavailable() -> None:  # T6
    target, notes = choose(plan(env(VDAGENT_WAREHOUSE_MODE="auto")), lambda t: "OperationalError")
    assert (target.origin, target.host, target.schema, target.sslmode) == ("local", "host.docker.internal", "re", None)
    assert notes == ["auto: AWS warehouse unavailable (OperationalError); falling back to the local snapshot"]


def test_auto_mode_needs_a_local_fallback_dsn() -> None:
    assert "VDAGENT_RE_WAREHOUSE_LOCAL_DB" in refused({"VDAGENT_WAREHOUSE_MODE": "auto", "VDAGENT_RE_WAREHOUSE_DB": AWS})


def test_auto_mode_applies_the_aws_rules_to_the_primary_and_the_local_rules_to_the_fallback() -> None:
    assert "not a remote" in refused(env(VDAGENT_WAREHOUSE_MODE="auto", VDAGENT_RE_WAREHOUSE_DB=LOCAL))
    assert "VDAGENT_RE_WAREHOUSE_LOCAL_DB" in refused(env(VDAGENT_WAREHOUSE_MODE="auto", VDAGENT_RE_WAREHOUSE_LOCAL_DB=AWS))


# ---- every mode -----------------------------------------------------------------------------------------------------


def test_an_unknown_mode_is_refused() -> None:
    assert "aws, local or auto" in refused(env(VDAGENT_WAREHOUSE_MODE="cloud"))


@pytest.mark.parametrize("dsn", [
    "postgresql://<user>:<password>@<rds-endpoint>.ap-southeast-1.rds.amazonaws.com:5432/cdw",
    "postgresql://cdw_reader:CHANGE_ME@cdw.abc123xyz.ap-southeast-1.rds.amazonaws.com:5432/cdw",
    "postgresql://your_user:your_password@cdw.abc123xyz.ap-southeast-1.rds.amazonaws.com:5432/cdw",
    "postgresql://user:password@cdw.abc123xyz.ap-southeast-1.rds.amazonaws.com:5432/cdw",
])
def test_placeholder_credentials_are_refused(dsn: str) -> None:  # T10
    text = refused(env(VDAGENT_WAREHOUSE_MODE="aws", VDAGENT_RE_WAREHOUSE_DB=dsn))
    assert "placeholder" in text and "VDAGENT_RE_WAREHOUSE_DB" in text


def test_a_placeholder_local_dsn_is_refused_too() -> None:
    text = refused(env(VDAGENT_WAREHOUSE_MODE="local",
                       VDAGENT_RE_WAREHOUSE_LOCAL_DB="postgresql://<user>:<password>@host.docker.internal:5433/cdw"))
    assert "placeholder" in text and "VDAGENT_RE_WAREHOUSE_LOCAL_DB" in text


def test_an_aws_dsn_without_a_password_is_refused() -> None:
    text = refused(env(VDAGENT_WAREHOUSE_MODE="aws",
                       VDAGENT_RE_WAREHOUSE_DB="postgresql://cdw_reader@cdw.abc123xyz.ap-southeast-1.rds.amazonaws.com:5432/cdw"))
    assert "password" in text


@pytest.mark.parametrize("dsn", ["", "./var/re_warehouse.db", "sqlite:///x.db"])
def test_a_mode_without_a_postgres_dsn_is_refused(dsn: str) -> None:
    text = refused({"VDAGENT_WAREHOUSE_MODE": "aws", "VDAGENT_RE_WAREHOUSE_DB": dsn})
    assert "VDAGENT_RE_WAREHOUSE_DB" in text and "postgresql://" in text


@pytest.mark.parametrize(("host", "local"), [
    ("host.docker.internal", True), ("localhost", True), ("127.0.0.1", True), ("::1", True), ("172.17.0.1", True),
    ("10.0.0.5", True), ("192.168.1.20", True), ("cdw-pg", True), ("pg.local", True),
    ("cdw.abc123xyz.ap-southeast-1.rds.amazonaws.com", False), ("dw.example.org", False), ("13.250.1.2", False),
])
def test_hosts_are_classified_local_or_remote(host: str, local: bool) -> None:
    assert is_local_host(host) is local
