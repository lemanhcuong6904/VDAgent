"""Artifacts: datasets, charts and reports that agents create through MCP tools, and the versioned artifact
envelopes of the six-agent DAG (`EnvelopeStore`), all owned per user.

`ArtifactService` is the entry point for both transports; `Artifacts` is its repository.

May import: `core`, `persistence`, `warehouse`.
"""

from vdagent_backend.artifacts.charts import CHART_KINDS, ChartError
from vdagent_backend.artifacts.envelopes import EnvelopeStore, verify_envelope
from vdagent_backend.artifacts.errors import ArtifactError, EnvelopeError
from vdagent_backend.artifacts.repository import Artifacts
from vdagent_backend.artifacts.service import ArtifactService

__all__ = [
    "CHART_KINDS",
    "ArtifactError",
    "ArtifactService",
    "Artifacts",
    "ChartError",
    "EnvelopeError",
    "EnvelopeStore",
    "verify_envelope",
]
