"""The MCP server at `/mcp`: the tool catalog, argument parsing, handlers, bearer auth and grants.

Agents reach it during a turn with the per-invocation token from `ctx.mcp`; each agent lists and
calls only the tools its plugin entry grants (`mcp_tools`). `reference` renders the agent-facing
tools reference (pdoc).

May import: `core`, `config`, `artifacts`, `warehouse`, `plugins`, `scopes`.
"""

from vdagent_backend.mcp.catalog import RESULT_FIELDS, TOOL_NAMES, TOOLS
from vdagent_backend.mcp.handlers import WRITABLE_TYPES, McpTools
from vdagent_backend.mcp.server import McpServer

__all__ = ["RESULT_FIELDS", "TOOLS", "TOOL_NAMES", "WRITABLE_TYPES", "McpServer", "McpTools"]
