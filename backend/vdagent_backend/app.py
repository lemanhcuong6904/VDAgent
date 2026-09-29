"""The composition root: `create_app(cfg)` wires every package; `app` is the lazy uvicorn entry point.

`uvicorn vdagent_backend.app:app` resolves `app` lazily (PEP 562), so importing this module (e.g.
from tests) has no side effects. The app MUST run as a single process.

`create_app` checks the plugin grants against the MCP catalog, then builds what needs no plugins:
the database engine (no connection yet), SSE bus, MCP tokens, `ArtifactService`, `Warehouse` and
the MCP server. The lifespan migrates the database (worker thread), loads the plugins, builds the
`Engine`, runs startup recovery and starts the MCP session manager; request-time objects live in
one `Services` on `app.state.services`. On exit: stop the engine, run the plugins' shutdown hooks,
dispose the database engine. `/mcp` is routed ahead of everything else; the built frontend is
served at `/` when `frontend_dist` exists.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from vdagent_backend import http
from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.config import Config, PluginSpec, load_config
from vdagent_backend.conversations import Messages, Tasks, Users
from vdagent_backend.core import EventBus, TokenRegistry
from vdagent_backend.mcp import TOOL_NAMES, McpServer, McpTools
from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.plugins import PluginManager
from vdagent_backend.runtime import Engine
from vdagent_backend.warehouse import Warehouse


def create_app(cfg: Config | None = None) -> FastAPI:
    """The Backend app for `cfg` (default: `load_config()`).

    Raises:
        ValueError: An enabled plugin entry grants an MCP tool that does not exist.
    """
    cfg = cfg or load_config()
    _check_grants(cfg.plugins)
    url = sqlite_url(cfg.backend_db)
    db = create_database(url)
    bus, tokens = EventBus(), TokenRegistry()
    artifacts = ArtifactService(db)
    mcp = McpServer(McpTools(artifacts, Warehouse(cfg.warehouse_db)), tokens)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(migrate, url)
        plugins = PluginManager()
        registry = await plugins.load(cfg.plugins)
        engine = Engine(cfg, db, bus, tokens, registry)
        app.state.services = http.Services(
            users=Users(db), tasks=Tasks(db), messages=Messages(db), artifacts=artifacts, engine=engine, bus=bus
        )
        try:
            await engine.recover()
            async with mcp.lifespan(registry):
                yield
        finally:
            await engine.stop()
            await plugins.close()
            await db.dispose()

    app = FastAPI(title="vdagent backend", lifespan=lifespan)
    http.install(app, Path(cfg.frontend_dist))
    mcp.install(app)
    return app


def _check_grants(specs: Sequence[PluginSpec]) -> None:
    """Every tool an enabled plugin entry grants must exist in the MCP catalog."""
    for spec in specs:
        unknown = sorted(spec.mcp_tools - TOOL_NAMES) if spec.enabled else []
        if unknown:
            names = ", ".join(f"'{name}'" for name in unknown)
            raise ValueError(f"plugin {spec.module}: mcp_tools names unknown MCP tools: {names}")


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    if name == "app":
        global _app
        if _app is None:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            _app = create_app()
        return _app
    raise AttributeError(name)
