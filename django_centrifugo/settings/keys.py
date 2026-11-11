"""Names supported in CENTRIFUGO_SETTINGS."""

from enum import StrEnum


class Settings(StrEnum):
    """Configuration keys for the Django integration."""

    proxy_key = "proxy_key"
    """Shared secret for incoming Centrifugo proxy requests."""
    connect_secret = "connect_secret"  # noqa: S105
    """Secret authenticating Centrifugo's HTTP connect proxy requests."""
    error_handler = "error_handler"
    """Optional error handler callable or import path."""
    consumers = "consumers"
    """Dotted paths to the concrete consumer classes enabled for RPCs and subscriptions."""
    client = "client"
    """Optional keyword arguments for pycent's synchronous and asynchronous clients."""
