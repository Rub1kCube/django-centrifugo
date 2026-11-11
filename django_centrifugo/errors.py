from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal


if TYPE_CHECKING:
    from django_centrifugo.contracts import RpcContext, SubscribeContext


@dataclass(frozen=True)
class ErrorContext:
    """Information passed to consumer and global gRPC proxy error handlers.

    Never expose the exception or its contents to clients.
    """

    endpoint: Literal["rpc", "subscribe", "stream", "stream_end"]
    """Proxy operation that failed."""

    kind: Literal["request", "unknown_action", "unknown_channel", "validation", "permission", "internal"]
    """Failure category."""

    exception: Exception
    """Original error; potentially contains sensitive information."""

    request: RpcContext | SubscribeContext | None = None
    """Request context, if it was parsed before the error occurred."""


@dataclass(frozen=True)
class ProxyError:
    """Safe application error returned to Centrifugo.

    Args:
        code: Centrifugo custom error code in the range 400–1999.
        message: Client-visible error message.
        temporary: Whether Centrifugo should treat the error as temporary.
    """

    code: int
    message: str
    temporary: bool = False


def default_error_handler(error: ErrorContext) -> ProxyError:
    """Return a safe Centrifugo error without exposing exception details.

    Args:
        error: Classified proxy failure.

    Returns:
        A client-safe error.
    """
    errors = {
        "request": (400, "Invalid proxy request"),
        "unknown_action": (404, "Unknown action"),
        "unknown_channel": (404, "Unknown channel"),
        "validation": (400, "Invalid action payload"),
        "permission": (403, "Permission denied"),
        "internal": (1000, "Internal error"),
    }
    code, message = errors[error.kind]
    return ProxyError(code, message)
