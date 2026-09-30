"""The local POC setup: compose pins every LLM-planned backend, and `docker/check-env.sh` fails fast (names only, never
values) when an agent `.env` is missing or a required key is empty."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "docker" / "check-env.sh"
AGENTS = ("orchestrator", "data", "insight", "compare", "chart", "report")
FULL = {"OPENAI_API_KEY": "sk-test-secret-value", "OPENAI_BASE_URL": "https://llm.test/v1", "LLM_MODEL": "m"}


def _services() -> dict[str, dict]:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]


@pytest.mark.parametrize("service", ["backend", "backend-live"])
def test_llm_planned_backends_pin_snapshot_and_semantic(service: str) -> None:
    env = _services()[service]["environment"]
    assert env["ORCH_SNAPSHOT_ID"] == "SNAP-2026-09-28" and env["ORCH_SEMANTIC_VERSION"] == "sc-1"
    assert env.get("ORCH_LLM", "on") != "off"  # the default stacks plan with the LLM


def test_live_stack_serves_the_ui_and_api_on_8022() -> None:
    live = _services()["backend-live"]
    assert live["environment"]["ORCH_LLM"] == "on" and live["ports"] == ["8022:8000"]


def _repo_with(tmp_path: Path, envs: dict[str, dict[str, str] | None]) -> Path:
    root = tmp_path / "repo"
    for agent in AGENTS:
        (root / "agents" / agent).mkdir(parents=True)
        (root / "agents" / agent / ".env.example").write_text("OPENAI_API_KEY=\n")
        values = envs.get(agent, {})
        if values is not None:
            (root / "agents" / agent / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return root


def _check(root: Path) -> subprocess.CompletedProcess[str]:
    assert shutil.which("bash")
    return subprocess.run(["bash", str(CHECK), str(root)], capture_output=True, text=True, check=False)


def test_complete_env_passes_without_printing_values(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, {a: FULL for a in ("orchestrator", "data", "report")} | {"insight": {"OPENAI_API_KEY": "sk-x"}})
    result = _check(root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sk-test-secret-value" not in result.stdout + result.stderr and "OK" in result.stdout


def test_missing_env_file_fails_with_the_fix(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, {"orchestrator": FULL, "data": FULL, "report": FULL, "chart": None})
    result = _check(root)
    assert result.returncode == 1 and "agents/chart/.env" in result.stdout and "make docker-env" in result.stdout


def test_empty_required_key_fails_naming_it_only(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, {"orchestrator": {**FULL, "OPENAI_API_KEY": ""}, "data": FULL, "report": FULL})
    result = _check(root)
    assert result.returncode == 1
    assert "agents/orchestrator/.env: OPENAI_API_KEY" in result.stdout and "sk-test" not in result.stdout


def test_insight_without_any_key_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    root = _repo_with(tmp_path, {"orchestrator": FULL, "data": FULL, "report": FULL})
    result = _check(root)
    assert result.returncode == 0 and "insight" in result.stdout and "template" in result.stdout
