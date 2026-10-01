"""Regenerate agents/manifests/*.json from the Python agent classes.

Usage (from the repo root):
    uv run --project agents python agents/gen_manifests.py          # write
    uv run --project agents python agents/gen_manifests.py --check  # fail if stale
"""

import importlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
ROSTER = {
    "orchestrator": "OrchestratorAgent",
    "data": "DataAgent",
    "compare": "CompareAgent",
    "insight": "InsightAgent",
    "visualize": "VisualizeAgent",
    "report": "ReportAgent",
}


def render(name: str, cls: str) -> str:
    manifest = getattr(importlib.import_module(name), cls).manifest.to_dict()
    # Paths are relative to the host working directory (repo root locally, /app in Docker).
    manifest["command"] = "uv"
    manifest["args"] = ["run", "--no-sync", "--project", "agents", "python", f"agents/{name}.py"]
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    check = "--check" in sys.argv[1:]
    stale = []
    for name, cls in ROSTER.items():
        target = ROOT / "manifests" / f"{name}.json"
        text = render(name, cls)
        if check:
            if not target.exists() or target.read_text() != text:
                stale.append(target.name)
        else:
            target.parent.mkdir(exist_ok=True)
            target.write_text(text)
    if stale:
        print("stale manifests: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
