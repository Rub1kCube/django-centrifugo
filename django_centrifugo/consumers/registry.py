from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ImproperlyConfigured
from django.urls.resolvers import RoutePattern
from django.utils.module_loading import import_string

from django_centrifugo.actions.errors import PayloadValidationError, UnknownActionError
from django_centrifugo.actions.rpc import RpcAction
from django_centrifugo.actions.stream import StreamAction
from django_centrifugo.consumers.consumer import Consumer
from django_centrifugo.settings import Settings, resolve_setting
from django_centrifugo.utils.type_inspection import generic_bindings


if TYPE_CHECKING:
    from django_centrifugo.serialization.base import SerializationBackend


@dataclass(frozen=True, slots=True)
class _ChannelEntry:
    consumer_class: type[Consumer[Any]]
    pattern: RoutePattern
    backend_class: type[SerializationBackend]
    data_annotation: Any
    _stream: StreamAction | None

    def get_stream(self) -> StreamAction | None:
        # This instance slot stores the descriptor itself, without invoking __get__.
        return self._stream  # pyright: ignore[reportReturnType]

    def validate_data(self, data: Any) -> Any:
        if self.data_annotation is Any:
            return data
        backend = self.backend_class()
        try:
            return backend.validate(self.data_annotation, data)
        except Exception as exc:
            raise PayloadValidationError(backend.format_validation_error(exc)) from exc


@dataclass(frozen=True, slots=True)
class _ConsumerRegistry:
    rpc_actions: Mapping[str, tuple[RpcAction, type[Consumer[Any]]]]
    channels: tuple[_ChannelEntry, ...]

    def resolve_action(self, name: str) -> tuple[RpcAction, type[Consumer[Any]]]:
        try:
            return self.rpc_actions[name]
        except KeyError as exc:
            raise UnknownActionError(name) from exc

    def resolve_channel(self, channel: str) -> tuple[_ChannelEntry, dict[str, Any]] | None:
        found = None
        for entry in self.channels:
            match = entry.pattern.match(channel)
            if match is None:
                continue
            if found is not None:
                msg = f"Channel {channel!r} matches multiple channel patterns"
                raise ImproperlyConfigured(msg)
            found = (entry, match[2])
        return found


def _validate_channel(channel: str) -> RoutePattern:
    try:
        pattern = RoutePattern(channel, is_endpoint=True)
        _ = pattern.regex
    except (ImproperlyConfigured, ValueError, TypeError) as exc:
        msg = f"Invalid channel pattern {channel!r}"
        raise ImproperlyConfigured(msg) from exc
    return pattern


def _consumer_backend(consumer: type[Consumer[Any]]) -> type[SerializationBackend]:
    parameters = getattr(consumer, "__parameters__", ())
    if consumer is Consumer or parameters or inspect.isabstract(consumer):
        msg = f"{consumer.__qualname__} must be a concrete Consumer subclass"
        raise ImproperlyConfigured(msg)
    if not isinstance(cast("Any", consumer.namespace), str):
        msg = f"{consumer.__qualname__}.namespace must be a string"
        raise ImproperlyConfigured(msg)
    backend = generic_bindings(consumer, Consumer).get(cast("Any", Consumer).__parameters__[0])
    if not isinstance(backend, type):
        msg = f"{consumer.__qualname__} must declare a Consumer backend class"
        raise ImproperlyConfigured(msg)
    return cast("type[SerializationBackend]", backend)


def _consumer_channels(consumer: type[Consumer[Any]]) -> tuple[str, ...]:
    if not isinstance(cast("Any", consumer.channel), str):
        msg = f"{consumer.__qualname__}.channel must be a string"
        raise ImproperlyConfigured(msg)
    if (
        isinstance(consumer.channels, (str, bytes))
        or not isinstance(cast("Any", consumer.channels), Sequence)
        or any(not isinstance(cast("Any", item), str) or not item for item in consumer.channels)
    ):
        msg = f"{consumer.__qualname__}.channels must be a sequence of nonempty strings"
        raise ImproperlyConfigured(msg)
    channels = (consumer.channel, *consumer.channels) if consumer.channel else tuple(consumer.channels)
    if len(set(channels)) != len(channels):
        msg = f"{consumer.__qualname__} declares duplicate channel patterns"
        raise ImproperlyConfigured(msg)
    return channels


def _load_consumer(path: str) -> type[Consumer[Any]]:
    try:
        consumer = import_string(path)
    except ImportError as exc:
        msg = f"Cannot import configured consumer {path!r}: {exc}"
        raise ImproperlyConfigured(msg) from exc
    if not isinstance(consumer, type) or not issubclass(consumer, Consumer):
        msg = f"Configured consumer {path!r} must be a Consumer subclass"
        raise ImproperlyConfigured(msg)
    return consumer


def _build_registry(paths: tuple[str, ...]) -> _ConsumerRegistry:
    rpc_actions: dict[str, tuple[RpcAction, type[Consumer[Any]]]] = {}
    channels: dict[str, _ChannelEntry] = {}
    consumers: set[type[Consumer[Any]]] = set()
    for path in paths:
        consumer = _load_consumer(path)
        if consumer in consumers:
            msg = f"Consumer {path!r} is configured more than once"
            raise ImproperlyConfigured(msg)
        consumers.add(consumer)
        backend_class = _consumer_backend(consumer)
        routes: dict[str, StreamAction | None] = dict.fromkeys(_consumer_channels(consumer))
        for method_name, declaration in consumer._discover_actions().items():  # noqa: SLF001
            action = declaration._configure(consumer, method_name, backend_class)  # noqa: SLF001
            if isinstance(action, RpcAction):
                if action.name in rpc_actions:
                    msg = (
                        f"RPC action {action.name!r} is declared by both "
                        f"{rpc_actions[action.name][1].__qualname__} and {consumer.__qualname__}"
                    )
                    raise ImproperlyConfigured(msg)
                rpc_actions[action.name] = (action, consumer)
            elif isinstance(action, StreamAction):
                if routes.get(action.channel) is not None:
                    msg = f"Multiple streams for channel {action.channel!r} in {consumer.__qualname__}"
                    raise ImproperlyConfigured(msg)
                routes[action.channel] = action
            else:
                msg = f"Unsupported action type {type(action).__qualname__} on {consumer.__qualname__}.{method_name}"
                raise ImproperlyConfigured(msg)
        annotation = consumer._configure_subscription(backend_class) if routes else Any  # noqa: SLF001
        for route, stream in routes.items():
            if route in channels:
                msg = (
                    f"Channel pattern {route!r} is declared by both "
                    f"{channels[route].consumer_class.__qualname__} and {consumer.__qualname__}"
                )
                raise ImproperlyConfigured(msg)
            channels[route] = _ChannelEntry(consumer, _validate_channel(route), backend_class, annotation, stream)
    return _ConsumerRegistry(MappingProxyType(rpc_actions), tuple(channels.values()))


@lru_cache(maxsize=1)
def _get_registry() -> _ConsumerRegistry:
    return _build_registry(resolve_setting(Settings.consumers))


def _clear_registry_cache() -> None:
    _get_registry.cache_clear()


def resolve_stream(channel: str) -> StreamAction | None:
    """Find a stream enabled by ``CENTRIFUGO_SETTINGS['consumers']``.

    The configured registry is loaded and cached on first use. Changing the
    Django setting invalidates the cache; running servers retain their snapshot.
    Channel patterns are compiled when the registry is built and checked for
    matches on lookup, including detection of overlapping routes.

    Args:
        channel: Concrete Centrifugo channel name, including any route parameters.

    Returns:
        The configured action, or ``None`` for unknown channels or routes without a stream.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If consumer configuration is invalid
            or multiple routes match the channel.
    """
    match = _get_registry().resolve_channel(channel)
    return match[0].get_stream() if match is not None else None
