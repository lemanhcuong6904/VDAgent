"""The built frontend at `/`, with an SPA fallback to `index.html` (only if the build exists)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.requests import Request
from starlette.responses import Response

from vdagent_backend.http.errors import error_response


def serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve files under `dist` and `index.html` for any other non-`/api` path; no-op without a build.

    Must be added after every other route: it is a catch-all.
    """
    index = dist / "index.html"
    if not index.is_file():
        return
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        if path == "api" or path.startswith("api/"):
            return error_response(404, "not_found", f"no route {request.url.path}")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
