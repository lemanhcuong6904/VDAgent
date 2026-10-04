"""scripts/check_secrets.py: the repository's offline secret scan (high-confidence patterns, values never printed).

Fake credentials are assembled at run time so this file never holds one and the scan of the repo stays clean."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_secrets.py"
SAMPLES = {
    "private-key": "-----BEGIN " + "PRIVATE KEY-----",
    "github-token": "ghp_" + "a" * 36,
    "aws-access-key": "AKIA" + "A" * 16,
    "provider-key": "sk-proj-" + "A" * 40,
    "slack-token": "xoxb-" + "1" * 24,
    "credential-url": "postgresql://user:" + "a" * 20 + "@db.example.org/cdw",
}


def _scanner():
    spec = importlib.util.spec_from_file_location("check_secrets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_secrets"] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.mark.parametrize("rule", sorted(SAMPLES))
def test_each_high_confidence_pattern_is_found_on_its_line_without_its_value(rule: str) -> None:
    findings = _scanner().secret_findings("example.py", "clean line\n" + SAMPLES[rule])
    assert [(f.rule, f.line) for f in findings] == [(rule, 2)]
    assert SAMPLES[rule] not in repr(findings)


def test_a_clean_file_has_no_findings() -> None:
    assert _scanner().secret_findings("app.py", "OPENAI_BASE_URL=https://api.openai.com/v1\nx = 1\n") == []


@pytest.mark.parametrize("text", [
    "postgresql://user:${POSTGRES_PASSWORD}@localhost/db",
    "postgresql://user:<your-password>@localhost/db",
    "postgresql://vdagent_reader:<password>@host.docker.internal:5433/cdw",
    "postgresql://user:YOUR_DB_PASSWORD@localhost/db",
    "postgresql://reader:short-pw@cdw.example.org:5432/cdw",  # under 12 characters: not high-confidence
])
def test_templates_and_short_placeholders_are_not_credentials(text: str) -> None:
    assert _scanner().secret_findings("README.md", text) == []


def test_replace_with_placeholders_are_allowed_only_in_env_example() -> None:
    text = "postgresql://user:" + "replace-with-" + "db-password@localhost/db"
    scanner = _scanner()
    assert scanner.secret_findings(".env.example", text) == []
    assert [f.rule for f in scanner.secret_findings("config.py", text)] == ["credential-url"]


def _repo(tmp_path: Path, files: dict[str, bytes], ignore: str = "") -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if ignore:
        (tmp_path / ".gitignore").write_text(ignore)
    for name, data in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    return tmp_path


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)], capture_output=True, text=True)


def test_a_clean_repository_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"a.py": b"x = 1\n", "img.bin": b"\0" + SAMPLES["aws-access-key"].encode()})
    result = _run(root)
    assert result.returncode == 0 and "PASS" in result.stdout  # the binary file is out of scope


def test_a_secret_fails_the_scan_and_is_redacted(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"src/conf.py": ("a = 1\nkey = '" + SAMPLES["aws-access-key"] + "'\n").encode()})
    result = _run(root)
    assert result.returncode == 1
    assert "src/conf.py:2: aws-access-key [REDACTED]" in result.stderr
    assert SAMPLES["aws-access-key"] not in result.stdout + result.stderr


def test_a_tracked_env_file_is_flagged_without_being_read(tmp_path: Path) -> None:
    root = _repo(tmp_path, {".env": ("TOKEN=" + SAMPLES["provider-key"]).encode(), ".env.example": b"TOKEN=\n"})
    result = _run(root)
    assert result.returncode == 1 and ".env:1: tracked-environment-file [REDACTED]" in result.stderr
    assert "provider-key" not in result.stderr and ".env.example" not in result.stderr


def test_ignored_files_are_not_scanned(tmp_path: Path) -> None:
    root = _repo(tmp_path, {".env": ("TOKEN=" + SAMPLES["provider-key"]).encode(), "a.py": b"x = 1\n"}, ignore=".env\n")
    assert _run(root).returncode == 0


def test_explicit_paths_are_scanned_instead_of_the_repository(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"clean.py": b"x = 1\n", "leak.py": SAMPLES["slack-token"].encode()})
    clean = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "clean.py"], capture_output=True, text=True)
    assert clean.returncode == 0
