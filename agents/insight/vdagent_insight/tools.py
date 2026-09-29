"""This turn's tools as LangChain `StructuredTool`s.

MCP tools come from this plugin's own `mcp_client.py` session: `langchain-mcp-adapters` needs
`mcp<2`, and every plugin shares the Backend's environment (locked to mcp 2.x). `send_to_agent` is
declared here but executed by `CtxBridge`, which routes it through `ctx.call_agent`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from vdagent_sdk import SEND_TO_AGENT, Peer

from .mcp_client import McpSession, McpTool, run_mcp_tool


def send_to_agent_tool(peers: Sequence[Peer]) -> StructuredTool:
    roster = "\n".join(f"- {p.name}: {p.description}" for p in peers)

    async def _bridged(**_: Any) -> str:
        raise RuntimeError("send_to_agent is executed by CtxBridge, never by the tool node")

    return StructuredTool(
        name=SEND_TO_AGENT,
        description=(
            "Send a message to another agent and wait for its reply. "
            f"The reply is returned as this tool's result. Agents:\n{roster}"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "enum": [p.name for p in peers]},
                "message": {
                    "type": "string",
                    "description": "Self-contained request, including any dataset ids it needs.",
                },
            },
            "required": ["agent", "message"],
        },
        coroutine=_bridged,
    )


def mcp_tool(session: McpSession, tool: McpTool) -> StructuredTool:
    async def _run(**arguments: Any) -> str:
        return await run_mcp_tool(session, tool.name, arguments)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.input_schema or {"type": "object", "properties": {}},
        coroutine=_run,
    )


def build_tools(session: McpSession, mcp_tools: Sequence[McpTool], peers: Sequence[Peer]) -> list[BaseTool]:
    tools: list[BaseTool] = [mcp_tool(session, t) for t in mcp_tools if t.name != SEND_TO_AGENT]
    if peers:
        tools.append(send_to_agent_tool(peers))
    return tools
