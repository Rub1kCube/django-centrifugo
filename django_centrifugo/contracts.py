from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RpcContext:
    """Fields received from Centrifugo, excluding the application payload."""

    client: str
    """Unique connection identifier."""

    transport: str
    """Client transport name."""

    protocol: str
    """Client protocol name."""

    encoding: str
    """Proxy payload encoding."""

    user: str
    """Authenticated connection user identifier, possibly empty."""

    method: str
    """Client RPC method."""

    meta: Any = None
    """Optional connection metadata."""


@dataclass(frozen=True, slots=True)
class SubscribeContext:
    """Subscription request information excluding its application payload."""

    client: str
    """Unique connection identifier."""

    transport: str
    """Client transport name."""

    protocol: str
    """Client protocol name."""

    encoding: str
    """Proxy payload encoding."""

    user: str
    """Authenticated connection user identifier, possibly empty."""

    channel: str
    """Complete requested Centrifugo channel."""

    params: dict[str, Any]
    """Values extracted by channel route converters."""

    meta: Any = None
    """Optional connection metadata."""
