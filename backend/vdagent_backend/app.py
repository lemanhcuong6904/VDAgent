"""FastAPI app factory and lifespan (§2.1).

`uvicorn vdagent_backend.app:app` resolves `app` lazily (PEP 562), so importing this module (e.g.
from tests) has no side effects. The app MUST run as a single process.

Lifespan: open backend.db (schema applied), load the agent plugins listed in `config.yaml`
(`plugins.py`; a failing plugin is logged and skipped), startup recovery (§4.6), MCP session
manager. On exit: stop the engine, then run the plugins' shutdown hooks. `/mcp` is routed ahead of
everything else; the built FE (`frontend_dist`) is served at `/` with an SPA fallback when the
directory exists.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.requests import Request
from starlette.responses import Response

from vdagent_backend.api import rest, sse
from vdagent_backend.api.deps import Services
from vdagent_backend.api.errors import error_response, install_error_handlers
from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.config import Config, PluginSpec, load_config
from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.runtime import Engine
from vdagent_backend.core import EventBus
from vdagent_backend.mcp.server import create_mcp
from vdagent_backend.mcp.tools import TOOL_NAMES
from vdagent_backend.plugins import PluginManager
from vdagent_backend.warehouse import Warehouse
from vdagent_backend.core import TokenRegistry


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    _check_grants(cfg.plugins)
    tokens = TokenRegistry()
    bus = EventBus()
    url = sqlite_url(cfg.backend_db)
    db = create_database(url)
    artifacts = ArtifactService(db)
    mcp = create_mcp(artifacts, Warehouse(cfg.warehouse_db), tokens)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(migrate, url)
        plugins = PluginManager()
        registry = await plugins.load(cfg.plugins)
        engine = Engine(cfg, db, bus, tokens, registry)
        app.state.services = Services(cfg=cfg, db=db, bus=bus, engine=engine, artifacts=artifacts)
        try:
            await engine.recover()
            async with mcp.lifespan(registry):
                yield
        finally:
            await engine.stop()
            await plugins.close()
            await db.dispose()

    app = FastAPI(title="vdagent backend", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(rest.router)
    app.include_router(sse.router)
    mcp.install(app)
    _serve_frontend(app, Path(cfg.frontend_dist))
    return app


def _check_grants(specs: Sequence[PluginSpec]) -> None:
    """Every tool an enabled plugin entry grants must exist in the MCP catalog."""
    for spec in specs:
        unknown = sorted(spec.mcp_tools - TOOL_NAMES) if spec.enabled else []
        if unknown:
            names = ", ".join(f"'{name}'" for name in unknown)
            raise ValueError(f"plugin {spec.module}: mcp_tools names unknown MCP tools: {names}")


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.is_file():
        return
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            return error_response(404, "not_found", f"no route {request.url.path}")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    if name == "app":
        global _app
        if _app is None:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            _app = create_app()
        return _app
    raise AttributeError(name)
