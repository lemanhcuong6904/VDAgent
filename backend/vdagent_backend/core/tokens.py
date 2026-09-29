"""In-memory per-invocation MCP bearer tokens.

The runtime issues a token when an invocation starts its turn and revokes it when the turn ends;
the MCP auth middleware resolves it to the caller identity. Tokens never outlive the process.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class McpIdentity:
    """Who is calling `/mcp`: the task's user, the agent in its turn, and that invocation."""

    user_id: str
    agent: str
    invocation_id: str


class TokenRegistry:
    """Issued tokens → identities."""

    def __init__(self) -> None:
        self._tokens: dict[str, McpIdentity] = {}

    def issue(self, user_id: str, agent: str, invocation_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = McpIdentity(user_id, agent, invocation_id)
        return token

    def resolve(self, token: str) -> McpIdentity | None:
        return self._tokens.get(token)

    def revoke(self, token: str | None) -> None:
        if token:
            self._tokens.pop(token, None)
