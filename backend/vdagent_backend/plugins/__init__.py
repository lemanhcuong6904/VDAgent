"""Agent plugins: loading `config.yaml` `plugins:` and the immutable agent registry with MCP grants.

May import: `core`, `config`.
"""

from vdagent_backend.plugins.loader import PluginManager
from vdagent_backend.plugins.registry import AgentRegistry, RegisteredAgent

__all__ = ["AgentRegistry", "PluginManager", "RegisteredAgent"]
