"""Artifact request errors."""


class ArtifactError(Exception):
    """An invalid artifact request; its message is the user-facing error text (MCP: `error: <text>`)."""


class EnvelopeError(ArtifactError, ValueError):
    """An artifact envelope the store refuses (unknown/foreign input, hash, snapshot or semantic mismatch, float)."""
