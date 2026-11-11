from __future__ import annotations

from typing import Any

import cent
from django.core.exceptions import ImproperlyConfigured

from django_centrifugo.settings import Settings, resolve_setting


__all__ = (
    "create_async_client",
    "create_client",
)


def _client_options() -> dict[str, Any]:
    options: dict[str, Any] | None = resolve_setting(Settings.client)
    if options is None:
        msg = "CENTRIFUGO_SETTINGS['client'] must be configured to use the server API"
        raise ImproperlyConfigured(msg)
    return options


def create_client() -> cent.Client:
    """Create a synchronous client using ``CENTRIFUGO_SETTINGS['client']``.

    The mapping supplies keyword arguments to pycent's ``cent.Client``.
    Each call creates a new client. The caller owns it and must close it,
    preferably with a ``with`` block. Reuse it for a series of API calls.
    A supplied ``http_client`` remains owned by its caller, as in pycent.

    Returns:
        A native pycent client, with pycent's results and exceptions.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If client settings are
            missing or pycent rejects the configuration.
    """
    options = _client_options()
    try:
        return cent.Client(**options)
    except (TypeError, cent.InvalidConfigError) as exc:
        msg = f"Invalid CENTRIFUGO_SETTINGS['client']: {exc}"
        raise ImproperlyConfigured(msg) from exc


def create_async_client() -> cent.AsyncClient:
    """Create an asynchronous client using ``CENTRIFUGO_SETTINGS['client']``.

    The mapping supplies keyword arguments to pycent's ``cent.AsyncClient``.
    Each call creates a new client. Create, use, and close it in the same
    event loop. The caller owns it and must await ``aclose()``, preferably
    using an ``async with`` block. A supplied ``http_client`` remains owned
    by its caller, as in pycent.

    Returns:
        A native pycent client, with pycent's results and exceptions.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If client settings are
            missing or pycent rejects the configuration.
    """
    options = _client_options()
    try:
        return cent.AsyncClient(**options)
    except (TypeError, cent.InvalidConfigError) as exc:
        msg = f"Invalid CENTRIFUGO_SETTINGS['client']: {exc}"
        raise ImproperlyConfigured(msg) from exc
