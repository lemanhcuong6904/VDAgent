"""The immutable agent registry: the only source of agent names, descriptions, objects and MCP grants."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from vdagent_sdk import Agent


@dataclass(frozen=True)
class RegisteredAgent:
    """One agent registered by a plugin.

    Attributes:
        name: Unique agent name (its chat, its stack, its `send_to_agent` target).
        description: One line shown to users and to peers.
        agent: The plugin's `Agent` object.
        plugin: The module that registered it.
        tools: MCP tool names granted to it (its plugin entry's `mcp_tools`).
    """

    name: str
    description: str
    agent: Agent
    plugin: str
    tools: frozenset[str] = frozenset()


class AgentRegistry:
    """Registered agents in registration order. Immutable."""

    def __init__(self, agents: Iterable[RegisteredAgent] = ()) -> None:
        self._agents: dict[str, RegisteredAgent] = {}
        for entry in agents:
            if entry.name in self._agents:
                raise ValueError(f"agent '{entry.name}' is registered twice")
            self._agents[entry.name] = entry

    def names(self) -> list[str]:
        return list(self._agents)

    def get(self, name: str) -> RegisteredAgent | None:
        return self._agents.get(name)

    def tools_for(self, agent: str) -> frozenset[str]:
        """The MCP tools `agent` may list and call; empty for an unknown agent."""
        entry = self._agents.get(agent)
        return entry.tools if entry is not None else frozenset()

    def __contains__(self, name: object) -> bool:
        return name in self._agents

    def __iter__(self) -> Iterator[RegisteredAgent]:
        return iter(self._agents.values())
