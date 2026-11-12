from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from django_centrifugo.actions.rpc import RpcAction


def resolve_action(name: str) -> RpcAction:
    """Find an RPC action enabled by ``CENTRIFUGO_SETTINGS['consumers']``.

    The configured registry is loaded and cached on first use. Changing the
    Django setting invalidates the cache; running servers retain their snapshot.

    Args:
        name: Complete RPC method name, including any consumer namespace prefix.

    Returns:
        The action configured for its consumer.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If consumer configuration is invalid.
        django_centrifugo.actions.errors.UnknownActionError: If no enabled action has the given name.
    """
    # Consumer imports action descriptors; defer the registry import to avoid a cycle.
    from django_centrifugo.consumers.registry import _get_registry  # noqa: PLC0415

    return _get_registry().resolve_action(name)[0]
