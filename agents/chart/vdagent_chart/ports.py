from __future__ import annotations

from typing import Protocol

from .contracts import ArtifactRef


class ArtifactStorePort(Protocol):
    def get_exact(self, ref: ArtifactRef) -> dict: ...
