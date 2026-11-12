from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, unique

from django.core.exceptions import PermissionDenied

from django_centrifugo.actions.errors import PayloadValidationError, UnknownActionError


@unique
class ErrorCode(IntEnum):
    """
    Built-in Centrifugo client error codes.

    See https://centrifugal.dev/docs/server/codes#client-error-codes.
    """

    INTERNAL = 100
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#internal>`_."""

    UNAUTHORIZED = 101
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#unauthorized>`_."""

    UNKNOWN_CHANNEL = 102
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#unknown-channel>`_."""

    PERMISSION_DENIED = 103
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#permission-denied>`_."""

    METHOD_NOT_FOUND = 104
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#method-not-found>`_."""

    ALREADY_SUBSCRIBED = 105
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#already-subscribed>`_."""

    LIMIT_EXCEEDED = 106
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#limit-exceeded>`_."""

    BAD_REQUEST = 107
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#bad-request>`_."""

    NOT_AVAILABLE = 108
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#not-available>`_."""

    TOKEN_EXPIRED = 109
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#token-expired>`_."""

    EXPIRED = 110
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#expired>`_."""

    TOO_MANY_REQUESTS = 111
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#too-many-requests>`_."""

    UNRECOVERABLE_POSITION = 112
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#unrecoverable-position>`_."""

    CONCURRENT_PAGINATION = 113
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#concurrent-pagination>`_."""


@unique
class UnsubscribeCode(IntEnum):
    """Built-in Centrifugo unsubscribe codes.

    See https://centrifugal.dev/docs/server/codes#client-unsubscribe-codes.
    """

    SERVER = 2000
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#unsubscribecodeserver>`_."""

    INSUFFICIENT_STATE = 2500
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#unsubscribecodeinsufficient>`_."""

    EXPIRED = 2501
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#unsubscribecodeexpired>`_."""

    STATE_INVALIDATED = 2502
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#unsubscribecodestateinvalidated>`_."""


@unique
class DisconnectCode(IntEnum):
    """Built-in Centrifugo disconnect codes.

    See https://centrifugal.dev/docs/server/codes#client-disconnect-codes.
    """

    CONNECTION_CLOSED = 3000
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectconnectionclosed>`_."""

    SHUTDOWN = 3001
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#shutdown>`_."""

    SERVER_ERROR = 3004
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectservererror>`_."""

    EXPIRED = 3005
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectexpired>`_."""

    SUBSCRIPTION_EXPIRED = 3006
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectsubexpired>`_."""

    SLOW = 3008
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectslow>`_."""

    WRITE_ERROR = 3009
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectwriteerror>`_."""

    INSUFFICIENT_STATE = 3010
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectinsufficientstate>`_."""

    FORCE_RECONNECT = 3011
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectforcereconnect>`_."""

    NO_PONG = 3012
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectnopong>`_."""

    TOO_MANY_REQUESTS = 3013
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnecttoomanyrequests>`_."""

    STATE_INVALIDATED = 3014
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectstateinvalidated>`_."""

    INVALID_TOKEN = 3500
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectinvalidtoken>`_."""

    BAD_REQUEST = 3501
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectbadrequest>`_."""

    STALE = 3502
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectstale>`_."""

    FORCE_NO_RECONNECT = 3503
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectforcenoreconnect>`_."""

    CONNECTION_LIMIT = 3504
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectconnectionlimit>`_."""

    CHANNEL_LIMIT = 3505
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectchannellimit>`_."""

    INAPPROPRIATE_PROTOCOL = 3506
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectinappropriateprotocol>`_."""

    PERMISSION_DENIED = 3507
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectpermissiondenied>`_."""

    NOT_AVAILABLE = 3508
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnectnotavailable>`_."""

    TOO_MANY_ERRORS = 3509
    """`Centrifugo <https://centrifugal.dev/docs/server/codes#disconnecttoomanyerrors>`_."""


class InvalidRequestError(ValueError):
    """The incoming Centrifugo proxy request is malformed or unsupported."""


class UnknownChannelError(LookupError):
    """The requested channel has no registered route."""


@dataclass(frozen=True)
class ProxyError:
    """Safe protocol error returned to Centrifugo.

    Args:
        code: Built-in Centrifugo error code (100–113) or custom code (400–1999).
        message: Client-visible error message.
        temporary: Whether Centrifugo should treat the error as temporary.
    """

    code: int
    message: str
    temporary: bool = False


def default_error_handler(error: Exception) -> ProxyError:
    """Return a safe Centrifugo error without exposing exception details.

    Args:
        error: Original exception raised while processing a request.

    Returns:
        A client-safe error.
    """
    if isinstance(error, InvalidRequestError):
        return ProxyError(ErrorCode.BAD_REQUEST, "bad request")
    if isinstance(error, UnknownActionError):
        return ProxyError(ErrorCode.METHOD_NOT_FOUND, "method not found")
    if isinstance(error, UnknownChannelError):
        return ProxyError(ErrorCode.UNKNOWN_CHANNEL, "unknown channel")
    if isinstance(error, PayloadValidationError):
        return ProxyError(ErrorCode.BAD_REQUEST, "bad request")
    if isinstance(error, PermissionDenied):
        return ProxyError(ErrorCode.PERMISSION_DENIED, "permission denied")
    return ProxyError(ErrorCode.INTERNAL, "internal server error", temporary=True)
