"""The REST error envelope `{"error": {"code": "<snake_case>", "message": "<text>"}}` and its handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from vdagent_backend.core import error_body


class ApiError(Exception):
    """An error response: HTTP `status` with the envelope's `code` and `message`."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    """A JSON response with the error envelope."""
    return JSONResponse(error_body(code, message), status_code=status)


def not_found(what: str) -> ApiError:
    """`404 not_found` with `<what> not found`."""
    return ApiError(404, "not_found", f"{what} not found")


def install_error_handlers(app: FastAPI) -> None:
    """Render `ApiError`, request validation errors and Starlette HTTP errors as the envelope."""

    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}" for err in exc.errors()
        )
        return error_response(422, "invalid_request", details or "invalid request")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))
