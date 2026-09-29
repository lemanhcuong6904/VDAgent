"""Artifact request errors."""


class ArtifactError(Exception):
    """An invalid artifact request; its message is the user-facing error text (MCP: `error: <text>`)."""
