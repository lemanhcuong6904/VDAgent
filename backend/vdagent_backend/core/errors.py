"""Error helpers shared by every layer: exception descriptions and the JSON error envelope."""

from typing import Any


def describe(exc: BaseException) -> str:
    """`<Type>: <message>` (or just `<Type>`) for logs and failure reasons.

    An exception group is described by its first leaf exception.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:  # pyright: ignore[reportUnknownMemberType]
        exc = exc.exceptions[0]  # pyright: ignore[reportUnknownVariableType]
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def error_body(code: str, message: str) -> dict[str, Any]:
    """The error envelope of the REST API and `/mcp`: `{"error": {"code", "message"}}`."""
    return {"error": {"code": code, "message": message}}
