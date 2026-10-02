"""The Docker setup: `make up` starts the whole product against the real PostgreSQL warehouse, from the project's own
compose file (never an unrelated `docker-compose.override.yml`), configured by one root `.env`. `docker/check-env.sh`
fails fast (names only, never values) when that `.env`, a required key or the warehouse DSN is missing; the synthetic
mock only runs through the explicit `make mock-up`."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "docker" / "check-env.sh"
REQUIRED = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_MODEL", "VDAGENT_RE_WAREHOUSE_DB", "ORCH_SNAPSHOT_ID",
            "ORCH_SEMANTIC_VERSION")
FULL = {"OPENAI_API_KEY": "sk-test-secret-value", "OPENAI_BASE_URL": "https://llm.test/v1", "LLM_MODEL": "m",
        "VDAGENT_RE_WAREHOUSE_DB": "postgresql://vdagent_reader:pg-secret@host.docker.internal:5433/cdw",
        "ORCH_SNAPSHOT_ID": "SNAP-20260630-01", "ORCH_SEMANTIC_VERSION": "3.1.0"}


def _compose() -> dict:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text())


def test_default_backend_is_the_llm_planned_product_on_8000_pinned_from_the_env() -> None:
    backend = _compose()["services"]["backend"]
    env = backend["environment"]
    assert "profiles" not in backend  # `make up` needs no profile
    assert env["ORCH_LLM"] == "on" and env["ORCH_DAG_TIMEOUT_S"] == "300"
    assert "ORCH_SNAPSHOT_ID" not in env and "ORCH_SEMANTIC_VERSION" not in env  # from .env, checked against the DW
    assert backend["ports"] == ["${VDAGENT_PORT:-8000}:8000"]


def test_default_stack_reads_the_root_env_and_keeps_data_in_its_own_volume() -> None:
    compose = _compose()
    for name in ("seed", "backend"):
        service = compose["services"][name]
        assert service["volumes"][0] == "app-var:/app/var"  # no root-owned ./var on the host
        assert all("agents/" not in str(v) for v in service["volumes"])  # no per-agent .env bind mounts
    assert compose["services"]["backend"]["env_file"] == [{"path": ".env", "required": True}]
    assert compose["volumes"]["app-var"]["name"] == "vdagent_real_var"  # never the mock's demo scopes


def test_the_backend_starts_only_after_the_real_warehouse_was_checked_from_inside_docker() -> None:
    services = _compose()["services"]
    check, backend = services["warehouse-check"], services["backend"]
    assert check["command"] == ["python", "docker/check_warehouse.py"]
    assert check["env_file"] == [{"path": ".env", "required": True}] and "profiles" not in check
    assert backend["depends_on"]["warehouse-check"] == {"condition": "service_completed_successfully"}
    for service in (check, backend):  # a PostgreSQL on the developer's machine is reachable as host.docker.internal
        assert service["extra_hosts"] == ["host.docker.internal:host-gateway"]


def test_targeting_backend_preserves_the_seed_and_warehouse_dependency_chain() -> None:
    backend = _compose()["services"]["backend"]
    assert backend["depends_on"] == {
        "seed": {"condition": "service_completed_successfully"},
        "warehouse-check": {"condition": "service_completed_successfully"},
    }


def test_the_app_volume_has_an_explicit_cross_platform_name() -> None:
    assert _compose()["volumes"]["app-var"]["name"] == "vdagent_real_var"


def test_the_seed_gives_real_scopes_and_never_builds_the_mock_warehouse() -> None:
    env = _compose()["services"]["seed"]["environment"]
    assert env["VDAGENT_SCOPE_PROFILE"] == "real" and env["SEED_RE_MOCK"] == "off"


def test_the_live_profile_is_gone() -> None:
    assert not {"seed-live", "backend-live"} & set(_compose()["services"])


def _make_dry_run(target: str) -> str:
    assert shutil.which("make")
    return subprocess.run(["make", "-n", "-C", str(REPO), target], capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("target", ["up", "down", "logs", "status", "restart", "build", "warehouse-check", "mock-up", "mock-down"])
def test_make_targets_use_only_the_project_compose_file(target: str) -> None:
    lines = [line for line in _make_dry_run(target).splitlines() if "docker compose" in line]
    assert lines and all("-f docker-compose.yml" in line for line in lines)  # never auto-merges an override


def test_make_up_checks_the_env_then_builds_and_waits_for_health() -> None:
    out = _make_dry_run("up")
    assert out.index("check-env.sh") < out.index("up -d --build --wait backend")
    assert "logs --no-log-prefix warehouse-check" in out  # a failed warehouse check is shown, not hidden


def test_make_has_the_short_lifecycle_commands() -> None:
    restart = _make_dry_run("restart")
    assert "make down" in restart and "make up" in restart
    assert "docker compose -f docker-compose.yml build" in _make_dry_run("build")
    assert "docker compose -f docker-compose.yml ps" in _make_dry_run("status")
    assert "check-env.sh" in _make_dry_run("warehouse-check")


def test_windows_wrapper_has_the_same_lifecycle_commands_and_preflight() -> None:
    script = (REPO / "dev.ps1").read_text()
    assert "docker-compose.yml" in script
    for command in ("up", "down", "logs", "status", "restart", "build", "warehouse-check"):
        assert command in script
    for key in REQUIRED:
        assert key in script
    assert "host.docker.internal" in script
    assert "localhost" in script
    assert "& make" not in script.lower() and "make.exe" not in script.lower()


def test_readme_documents_the_raw_windows_compose_command_and_power_shell_reset() -> None:
    readme = (REPO / "README.md").read_text()
    raw = "docker compose -f docker-compose.yml up -d --build --wait backend"
    assert raw in readme
    assert "PowerShell 5.1" in readme
    assert "docker volume rm vdagent_real_var" in readme


def test_readme_explains_how_to_build_the_real_warehouse_dsn_without_a_secret() -> None:
    readme = (REPO / "README.md").read_text()
    required = (
        "Cách xác định `VDAGENT_RE_WAREHOUSE_DB`",
        "postgresql://<user>:<password>@<host>:<port>/<database>",
        "host.docker.internal:5433",
        "docker ps",
        "docker port cdw-pg",
        "docker exec cdw-pg printenv POSTGRES_DB",
        "vdagent_reader",
        "docker/warehouse/apply-views.sh",
        "make warehouse-check",
        ".\\dev.ps1 warehouse-check",
        "password authentication failed",
    )
    assert all(item in readme for item in required)
    assert "vdagent_reader:cdw@" not in readme


def test_the_mock_only_starts_explicitly() -> None:
    assert "--profile offline up -d --build --wait backend-offline" in _make_dry_run("mock-up")
    assert "offline" not in _make_dry_run("up")


def _seed(tmp_path: Path, seed_re_mock: str) -> list[str]:
    bin_dir, log = tmp_path / "bin", tmp_path / "calls.log"
    bin_dir.mkdir()
    (bin_dir / "python").write_text(f'#!/bin/sh\necho "$*" >> {log}\n')
    (bin_dir / "python").chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "SEED_RE_MOCK": seed_re_mock}
    subprocess.run(["sh", str(REPO / "docker" / "seed-if-missing.sh")], cwd=tmp_path, env=env, check=True, capture_output=True)
    return log.read_text().splitlines()


def test_the_seed_skips_the_mock_warehouse_when_told_to(tmp_path: Path) -> None:
    calls = _seed(tmp_path, "off")
    assert calls == ["data/seed_warehouse.py", "data/seed_users.py"]


def test_the_seed_still_builds_the_mock_for_the_mock_stack(tmp_path: Path) -> None:
    assert "data/seed_re_warehouse.py" in _seed(tmp_path, "")


def test_env_example_lists_every_required_key() -> None:
    example = (REPO / ".env.example").read_text()
    assert all(f"\n{key}=" in f"\n{example}" for key in REQUIRED)


def _repo_with(tmp_path: Path, values: dict[str, str] | None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    if values is not None:
        (root / ".env").write_text("# comment\n" + "".join(f"{k}={v}\n" for k, v in values.items()))
    return root


def _check(root: Path) -> subprocess.CompletedProcess[str]:
    assert shutil.which("bash")
    return subprocess.run(["bash", str(CHECK), str(root)], capture_output=True, text=True, check=False)


def test_complete_env_passes_without_printing_values(tmp_path: Path) -> None:
    result = _check(_repo_with(tmp_path, FULL))
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout + result.stderr
    assert "sk-test-secret-value" not in out and "pg-secret" not in out and "OK" in result.stdout


def test_missing_env_file_fails_with_the_fix(tmp_path: Path) -> None:
    result = _check(_repo_with(tmp_path, None))
    assert result.returncode == 1 and "cp .env.example .env" in result.stdout


@pytest.mark.parametrize("key", REQUIRED)
def test_empty_required_key_fails_naming_it_only(tmp_path: Path, key: str) -> None:
    result = _check(_repo_with(tmp_path, {**FULL, key: ""}))
    assert result.returncode == 1 and f".env: {key}" in result.stdout
    assert "sk-test" not in result.stdout + result.stderr and "pg-secret" not in result.stdout + result.stderr


def test_without_a_warehouse_dsn_the_error_says_the_real_warehouse_is_required(tmp_path: Path) -> None:
    result = _check(_repo_with(tmp_path, {**FULL, "VDAGENT_RE_WAREHOUSE_DB": ""}))
    assert "ERROR: Real warehouse is required. Set VDAGENT_RE_WAREHOUSE_DB in .env." in result.stdout


@pytest.mark.parametrize("dsn", ["./var/re_warehouse.db", "sqlite:///var/re_warehouse.db"])
def test_a_sqlite_warehouse_is_refused(tmp_path: Path, dsn: str) -> None:
    result = _check(_repo_with(tmp_path, {**FULL, "VDAGENT_RE_WAREHOUSE_DB": dsn}))
    assert result.returncode == 1 and "postgresql://" in result.stdout


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_loopback_warehouse_host_is_refused_with_the_docker_fix(tmp_path: Path, host: str) -> None:
    dsn = f"postgresql://vdagent_reader:pg-secret@{host}:5433/cdw"
    result = _check(_repo_with(tmp_path, {**FULL, "VDAGENT_RE_WAREHOUSE_DB": dsn}))
    assert result.returncode == 1 and "host.docker.internal" in result.stdout and "pg-secret" not in result.stdout


def test_quoted_values_count_as_set(tmp_path: Path) -> None:
    result = _check(_repo_with(tmp_path, {k: f'"{v}"' for k, v in FULL.items()}))
    assert result.returncode == 0, result.stdout
