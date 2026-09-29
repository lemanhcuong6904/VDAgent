"""The REST API, the SSE stream and the frontend mount.

Handlers parse input, call a domain repository, `ArtifactService` or the runtime `Engine`, and
return DTOs. Every route but `/api/users` requires a known user (`X-User-Id` header, or the
`user_id` query parameter for SSE); errors use the `{"error": {"code", "message"}}` envelope.

May import: `core`, `conversations`, `artifacts`, `runtime`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from vdagent_backend.http import agents, artifacts, events, tasks, users
from vdagent_backend.http.deps import Services
from vdagent_backend.http.errors import install_error_handlers
from vdagent_backend.http.frontend import serve_frontend


def install(app: FastAPI, frontend_dist: Path) -> None:
    """Add the error handlers, every `/api` route and (last, a catch-all) the frontend to `app`."""
    install_error_handlers(app)
    for module in (users, agents, tasks, artifacts, events):
        app.include_router(module.router)
    serve_frontend(app, frontend_dist)


__all__ = ["Services", "install"]
