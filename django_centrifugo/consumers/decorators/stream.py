"""Declare personalized subscription streams on consumers."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

from django.core.exceptions import ImproperlyConfigured

from django_centrifugo.actions.base import BaseAction
from django_centrifugo.actions.stream import StreamAction


FunctionT = TypeVar("FunctionT", bound=Callable[..., Any])


def stream(
    channel: str,
    *,
    close_on_complete: bool = True,
    summary: str | None = None,
    description: str | None = None,
    tags: frozenset[str] | None = None,
    deprecated: bool = False,
) -> Callable[[FunctionT], FunctionT]:
    """Declare an async generator as a channel's per-subscription stream.

    A decorator wrapping the method must itself be an async generator function.
    Its public signature must accept ``data`` and ``context`` as keyword
    arguments and provide the annotated input and output types.

    The route is registered when the containing consumer is loaded from
    ``CENTRIFUGO_SETTINGS['consumers']``. After ``on_subscribe``
    accepts a request, the generator receives the same validated ``data`` and
    ``context`` and yields model instances or dictionaries validated against the
    annotated model.

    Args:
        channel: Channel route with optional Django path converters.
        close_on_complete: Close the subscription stream after the generator
            finishes. If false, keep the subscription open until disconnected.
        summary: Short description. Defaults to the first docstring paragraph.
        description: Detailed description. Defaults to the full method docstring.
        tags: Documentation tags; copied into an immutable tuple.
        deprecated: Whether the action is deprecated in documentation.

    Returns:
        A decorator creating a stream action descriptor. Access through a consumer
        instance binds the original method for ordinary direct calls.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If the arguments or method are invalid.
    """
    if not isinstance(cast("Any", channel), str) or not channel:
        msg = "Stream 'channel' must be a nonempty string"
        raise ImproperlyConfigured(msg)

    if type(cast("Any", close_on_complete)) is not bool:
        msg = "'close_on_complete' must be a boolean"
        raise ImproperlyConfigured(msg)

    def decorate(method: FunctionT) -> FunctionT:
        if isinstance(cast("Any", method), BaseAction):
            msg = "A method cannot have multiple action declarations"
            raise ImproperlyConfigured(msg)

        if not inspect.isasyncgenfunction(method):
            msg = "A stream method, including any decorator wrapper, must be an async generator"
            raise ImproperlyConfigured(msg)

        return cast(
            "FunctionT",
            StreamAction(
                channel,
                method=method,
                close_on_complete=close_on_complete,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
            ),
        )

    return decorate
