from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Final

from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string

from django_centrifugo.settings.defaults import DEFAULT_SETTINGS
from django_centrifugo.settings.keys import Settings


PREFIX_NAME_SETTING: Final = "CENTRIFUGO_SETTINGS"


def _user_settings() -> Mapping[str, Any]:
    configuration = getattr(django_settings, PREFIX_NAME_SETTING, {})
    if not isinstance(configuration, Mapping):
        message = f"{PREFIX_NAME_SETTING} must be a mapping"
        raise ImproperlyConfigured(message)
    if "action_modules" in configuration:
        message = (
            "CENTRIFUGO_SETTINGS['action_modules'] has been removed; use 'consumers' with paths to classes, "
            "for example ['myapp.consumers.ChatConsumer']"
        )
        raise ImproperlyConfigured(message)
    for key in configuration:
        if key not in DEFAULT_SETTINGS:
            message = f"Unknown {PREFIX_NAME_SETTING} key: {key!r}"
            raise ImproperlyConfigured(message)
    return configuration


def _import(value: Any, setting: Settings) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return import_string(value)
    except ImportError as exc:
        message = f"Cannot import {PREFIX_NAME_SETTING}[{setting.value!r}] ({value!r}): {exc}"
        raise ImproperlyConfigured(message) from exc


def _client_config(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        msg = "CENTRIFUGO_SETTINGS['client'] must be a mapping with string keys"
        raise ImproperlyConfigured(msg)
    return dict(value)


@lru_cache(maxsize=len(Settings))
def _resolve_setting(setting: Settings) -> Any:
    value = _user_settings().get(setting, DEFAULT_SETTINGS[setting])
    if setting == Settings.error_handler:
        value = _import(value, setting)
        if value is not None and not callable(value):
            msg = "CENTRIFUGO_SETTINGS['error_handler'] must be callable"
            raise ImproperlyConfigured(msg)
    elif setting == Settings.consumers:
        if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in value):
            msg = "CENTRIFUGO_SETTINGS['consumers'] must be a list or tuple of nonempty consumer class paths"
            raise ImproperlyConfigured(msg)
        value = tuple(value)
    elif setting == Settings.client:
        value = _client_config(value)
    elif not isinstance(value, str):
        msg = f"CENTRIFUGO_SETTINGS[{setting.value!r}] must be a string"
        raise ImproperlyConfigured(msg)
    return value


def resolve_setting(setting: Settings | str) -> Any:
    """Resolve and validate a setting; Django setting changes clear the cache."""
    try:
        key = Settings(setting)
    except ValueError as exc:
        message = f"Unknown {PREFIX_NAME_SETTING} key: {setting!r}"
        raise ImproperlyConfigured(message) from exc
    return _resolve_setting(key)


def clear_settings_cache() -> None:
    """Invalidate settings and consumer registries for subsequent lookups.

    Running gRPC servers retain their existing consumer registry snapshots.
    Django's ``setting_changed`` signal calls this automatically when
    ``CENTRIFUGO_SETTINGS`` changes through ``override_settings``.
    """
    # Registry construction uses settings, so import its invalidator only when needed.
    from django_centrifugo.consumers.registry import _clear_registry_cache  # noqa: PLC0415

    _resolve_setting.cache_clear()
    _clear_registry_cache()


@receiver(setting_changed, dispatch_uid="django_centrifugo.settings.reload")
def _reload_settings(*, setting: str, **_kwargs: Any) -> None:
    if setting == PREFIX_NAME_SETTING:
        clear_settings_cache()
