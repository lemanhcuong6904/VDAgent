from __future__ import annotations

import json
from pathlib import Path

from .contracts import ArtifactRef
from .errors import ChartError

ARTIFACTS_FILE = Path(__file__).parent / "demo" / "artifacts.json"


class FixtureArtifactStore:
    """Read-only exact-version store used in place of upstream agents for the demo."""

    def __init__(self, artifacts: list[dict]) -> None:
        self._artifacts = {(item["artifact_id"], item["version"]): item for item in artifacts}

    @classmethod
    def demo(cls) -> "FixtureArtifactStore":
        return cls(json.loads(ARTIFACTS_FILE.read_text(encoding="utf-8"))["artifacts"])

    def get_exact(self, ref: ArtifactRef) -> dict:
        if not ref.artifact_id or not isinstance(ref.version, int):
            raise ChartError("DEP-001", "artifact reference must pin a non-empty id and integer version", "dependency")
        artifact = self._artifacts.get((ref.artifact_id, ref.version))
        if artifact is None:
            raise ChartError("DEP-002", f"artifact {ref.artifact_id}@{ref.version} not found", "dependency")
        if ref.expected_hash and artifact["content_hash"] != ref.expected_hash:
            raise ChartError("DEP-003", f"artifact hash mismatch for {ref.artifact_id}@{ref.version}", "dependency")
        return artifact
