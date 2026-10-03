"""Offline secret scan of the repository: high-confidence patterns only; matched values are never printed.

Usage: python scripts/check_secrets.py [--root DIR] [PATH ...]      (also: make secret-check)

Scans every file Git would commit (`git ls-files --cached --others --exclude-standard`), or only the PATHs given.
Binary files are skipped; a tracked or untracked-but-not-ignored real `.env` file is reported without being opened.
Exit codes: 0 PASS, 1 findings (`<file>:<line>: <rule> [REDACTED]` on stderr), 2 the input could not be read in full
(no PASS is claimed). Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{60,255})\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("provider-key", re.compile(r"\bsk-(?:proj-|ant-api\d{2}-)?[A-Za-z0-9_-]{32,255}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,255}\b")),
    # a password of 12+ characters inside a URL; shorter values are treated as placeholders (high confidence only)
    ("credential-url", re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|https?)://[^\s/:@]+:([^\s/@]{12,})@")),
)
TEMPLATE = re.compile(r"^(?:\$\{[^}]+\}|<[^>]+>|YOUR_[A-Z_]+)$")
ENV_EXAMPLE_PLACEHOLDER = re.compile(r"^replace-with-[a-z-]+$")
REAL_ENV_FILE = re.compile(r"^(?:.+/)?\.env(?:\.(?!example$).+)?$")


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str


def secret_findings(path: str, text: str) -> list[Finding]:
    """The high-confidence matches in `text` (the content of `path`), as file/line/rule only."""
    found: list[Finding] = []
    for rule, pattern in PATTERNS:
        for match in pattern.finditer(text):
            if rule == "credential-url":
                password = match.group(1)
                if TEMPLATE.match(password):
                    continue
                if Path(path).name == ".env.example" and ENV_EXAMPLE_PLACEHOLDER.match(password):
                    continue
            found.append(Finding(path, text.count("\n", 0, match.start()) + 1, rule))
    return found


def repository_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                         capture_output=True, check=True).stdout.decode()
    return sorted({p for p in out.split("\0") if p and (root / p).is_file()})


def scan(root: Path, paths: list[str]) -> tuple[int, list[Finding]]:
    """`(text files scanned, findings)`. Raises OSError/ValueError when a file cannot be read in full."""
    scanned, findings = 0, []
    for path in paths:
        if REAL_ENV_FILE.match(path):
            findings.append(Finding(path, 1, "tracked-environment-file"))  # never open a credential file
            continue
        target = (root / path).resolve()
        if root.resolve() not in target.parents:
            raise ValueError(f"{path}: outside the repository")
        if target.stat().st_size > MAX_BYTES:
            raise ValueError(f"{path}: larger than {MAX_BYTES} bytes")
        data = target.read_bytes()
        if b"\0" in data:
            continue  # binary content is outside this text scanner's scope
        scanned += 1
        findings.extend(secret_findings(path, data.decode("utf-8", errors="replace")))
    return scanned, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("paths", nargs="*", help="files to scan (default: every file Git would commit)")
    args = parser.parse_args(argv)
    try:
        paths = args.paths or repository_files(args.root)
        scanned, findings = scan(args.root, paths)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Secret scan could not read the full input ({type(exc).__name__}); no PASS claimed", file=sys.stderr)
        return 2
    for f in findings:
        print(f"{f.file}:{f.line}: {f.rule} [REDACTED]", file=sys.stderr)
    if findings:
        return 1
    print(f"Secret pattern scan PASS ({scanned} text files; ignored files, history and binaries are not scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
