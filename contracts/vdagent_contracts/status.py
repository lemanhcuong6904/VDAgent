"""Map the status words of each spec onto the one artifact status vocabulary (R-04, X-04, X-17)."""

from __future__ import annotations

from vdagent_contracts.envelope import ArtifactStatus

_ALIASES: dict[str, ArtifactStatus] = {
    # Data v02 §8.2
    "VALIDATED": ArtifactStatus.VALID,
    # Chart: validated / partial / failed
    "validated": ArtifactStatus.VALID,
    "partial": ArtifactStatus.PARTIAL,
    "failed": ArtifactStatus.INVALID,
}


def to_envelope_status(word: str) -> ArtifactStatus:
    """Canonical status for a producer's status word; unknown words raise ValueError."""
    if word in _ALIASES:
        return _ALIASES[word]
    return ArtifactStatus(word)
