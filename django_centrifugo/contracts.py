from dataclasses import dataclass, field
from typing import Any, Literal


type ClientTransport = Literal["websocket", "sockjs", "sse", "http_stream", "webtransport"]
"""Bidirectional client transports used by RPC and subscription proxies."""

type ClientProtocol = Literal["json", "protobuf"]
"""Client protocol formats supported by Centrifugo."""

type ProxyEncoding = Literal["json", "binary"]
"""Payload encodings defined by the Centrifugo proxy protocol."""


@dataclass(kw_only=True, frozen=True, slots=True)
class RpcContext:
    """Fields received from Centrifugo, excluding the application payload.

    https://centrifugal.dev/docs/server/proxy#rpcrequest
    """

    client: str
    """Unique connection identifier."""

    transport: ClientTransport
    """Client transport name."""

    protocol: ClientProtocol
    """Client protocol name."""

    encoding: ProxyEncoding
    """Proxy payload encoding."""

    user: str
    """Authenticated connection user identifier, possibly empty."""

    method: str
    """Client RPC method."""

    meta: Any = None
    """Optional connection metadata."""

    labels: dict[str, str] = field(default_factory=dict)
    """Connection labels attached during authentication (Centrifugo PRO only)."""


@dataclass(frozen=True, slots=True)
class SubscribeContext:
    """Subscription request information excluding its application payload.

    https://centrifugal.dev/docs/server/proxy#subscriberequest
    """

    client: str
    """Unique connection identifier."""

    transport: ClientTransport
    """Client transport name."""

    protocol: ClientProtocol
    """Client protocol name."""

    encoding: ProxyEncoding
    """Proxy payload encoding."""

    user: str
    """Authenticated connection user identifier, possibly empty."""

    channel: str
    """Complete requested Centrifugo channel."""

    params: dict[str, Any]
    """Values extracted by channel route converters."""

    meta: Any = None
    """Optional connection metadata."""

    token: str = ""
    """Subscription JWT supplied by the client, or an empty string if absent."""

    labels: dict[str, str] = field(default_factory=dict)
    """Connection labels attached during authentication (Centrifugo PRO only)."""
