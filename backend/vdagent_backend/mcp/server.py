"""The MCP server at `/mcp`: streamable HTTP via the official SDK's low-level `Server`.

The low-level `Server` lets `tools/list` and `tools/call` see the per-request caller identity, so
both are filtered by the caller agent's grants (`AgentRegistry.tools_for`). The SDK session manager
runs stateless: every HTTP request is self-contained and authenticated on its own, so a revoked
token stops working immediately. Until `lifespan` runs, `/mcp` answers `503 mcp_unavailable`.

Usage (FastAPI app):

    mcp = McpServer(McpTools(artifacts, warehouse), tokens)
    mcp.install(app)
    async with mcp.lifespan(registry):  # inside the app lifespan
        yield
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import mcp_types as types
from fastapi import FastAPI
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from vdagent_backend.core import TokenRegistry, error_body
from vdagent_backend.mcp.auth import BearerAuth, current_identity
from vdagent_backend.mcp.catalog import TOOLS
from vdagent_backend.mcp.handlers import McpTools, tool_error
from vdagent_backend.plugins import AgentRegistry

MCP_PATHS = ("/mcp", "/mcp/")


class McpServer:
    """Serves the catalog's tools to the agents that are granted them."""

    def __init__(self, tools: McpTools, tokens: TokenRegistry) -> None:
        self._tools = tools
        self._server: Server[Any] = Server(
            "vdagent",
            version="0.1.0",
            instructions="vdagent warehouse and artifact tools.",
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )
        self._manager: StreamableHTTPSessionManager | None = None
        self._registry = AgentRegistry()
        self._endpoint = BearerAuth(tokens, self._handle)

    async def _list_tools(
        self, ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        identity = current_identity.get()
        granted = self._registry.tools_for(identity.agent) if identity else frozenset()
        return types.ListToolsResult(tools=[tool for tool in TOOLS if tool.name in granted])

    async def _call_tool(self, ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        identity = current_identity.get()
        if identity is None:
            return tool_error("unauthenticated")
        granted = self._registry.tools_for(identity.agent)
        return await self._tools.call(identity, granted, params.name, params.arguments or {})

    async def _handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        manager = self._manager
        if manager is None:
            response = JSONResponse(error_body("mcp_unavailable", "MCP server is not running"), status_code=503)
            await response(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(self, registry: AgentRegistry) -> AsyncIterator[None]:
        """Serve `/mcp` with the grants of `registry`; the FastAPI app lifespan MUST enter this."""
        # A session manager runs once; a fresh one per lifespan keeps this re-enterable.
        manager = StreamableHTTPSessionManager(app=self._server, stateless=True)
        async with manager.run():
            self._manager, self._registry = manager, registry
            try:
                yield
            finally:
                self._manager, self._registry = None, AgentRegistry()

    def install(self, app: FastAPI) -> None:
        """Route exactly `/mcp` and `/mcp/` (no slash redirect) ahead of any catch-all route."""
        for path in MCP_PATHS:
            app.router.routes.insert(0, Route(path, endpoint=self._endpoint))
