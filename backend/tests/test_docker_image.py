"""What the image carries: the application and the three seeders, never the raw CSV packs or the retired warehouse
pipeline; the test stage also carries the repo files its Docker-setup tests read (README.md, dev.ps1). The mock
warehouse is named explicitly by the offline stack only; the product stack takes the real DSN from .env."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SEEDERS = ("data/seed_warehouse.py", "data/seed_re_warehouse.py", "data/seed_users.py")
MOCK = "./var/re_warehouse.db"


def _stages() -> dict[str, list[str]]:
    """Each stage of Dockerfile.python → the sources of its COPY instructions (without --from copies)."""
    stages: dict[str, list[str]] = {}
    current = ""
    for line in (REPO / "Dockerfile.python").read_text().splitlines():
        if m := re.match(r"FROM\s+\S+\s+AS\s+(\S+)", line, re.IGNORECASE):
            current = m.group(1)
            stages[current] = []
        elif line.startswith("COPY ") and "--from" not in line:
            stages[current].extend(line.split()[1:-1])
    return stages


def test_no_stage_copies_the_whole_data_folder_or_the_warehouse_folder() -> None:
    for stage, sources in _stages().items():
        assert "data/" not in sources and "data" not in sources, stage
        assert not any(s.startswith("warehouse") for s in sources), stage


def test_the_runtime_and_test_images_carry_exactly_the_seeders_from_data() -> None:
    stages = _stages()
    for stage in ("runtime", "test"):
        assert sorted(s for s in stages[stage] if s.startswith("data/")) == sorted(SEEDERS), stage


def test_every_copied_data_file_exists() -> None:
    for stage, sources in _stages().items():
        for source in (s for s in sources if s.startswith("data/")):
            assert (REPO / source).is_file(), f"{stage}: {source}"


def test_the_test_image_carries_the_files_its_docker_setup_tests_read() -> None:
    sources = _stages()["test"]
    assert "README.md" in sources and "dev.ps1" in sources


def test_the_build_context_leaves_out_the_csv_packs_but_keeps_the_seeders() -> None:
    ignore = (REPO / ".dockerignore").read_text().splitlines()
    assert "warehouse" in ignore and "data/*" in ignore
    assert all(f"!{seeder}" in ignore for seeder in SEEDERS)


def _services() -> dict:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]


def test_only_the_offline_stack_names_the_mock_warehouse() -> None:
    services = _services()
    for name in ("seed-offline", "backend-offline"):
        assert services[name]["environment"]["VDAGENT_RE_WAREHOUSE_DB"] == MOCK, name
    for name in ("seed", "backend", "warehouse-check"):
        assert "VDAGENT_RE_WAREHOUSE_DB" not in (services[name].get("environment") or {}), name
