"""Offline Compare demo and JSON artifact export.

Run: uv run python -m vdagent_compare.demo --question "..."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .vh_chat import HELP, parse_request, render
from .vh_service import CompareService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VHOP Compare v5.1 demo")
    parser.add_argument("--question", default="So sánh căn ZURICH-20.022 với các căn tương đồng")
    parser.add_argument("--request-file", type=Path, help="JSON Compare request; overrides --question")
    parser.add_argument("--artifact-out", type=Path, help="write both JSON artifacts to this file")
    parser.add_argument("--json", action="store_true", help="print raw JSON artifacts")
    args = parser.parse_args(argv)
    if args.request_file:
        request = json.loads(args.request_file.read_text(encoding="utf-8"))
    else:
        request = parse_request(args.question)
    if not isinstance(request, dict):
        parser.error(HELP)
    result = CompareService().run(request)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.artifact_out:
        args.artifact_out.parent.mkdir(parents=True, exist_ok=True)
        args.artifact_out.write_text(encoded + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(encoded if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
