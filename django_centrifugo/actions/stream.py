from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing
from typing import TYPE_CHECKING, Any, get_args, get_origin, override

from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypeForm

from django_centrifugo.actions.base import BaseAction
from django_centrifugo.serialization.output import _output_model, _validate_output


if TYPE_CHECKING:
    from django_centrifugo.contracts import SubscribeContext
    from django_centrifugo.serialization.base import SerializationBackend


class StreamAction(BaseAction):
    """A stream declaration or a stream configured for a concrete consumer.

    Stream and RPC actions share the consumer registration process. The
    configured action receives the already validated subscription data and
    validates each yielded value against the output model before returning it.
    Direct access through a consumer instance calls the original generator.

    Args:
        channel: Channel route with optional Django path converters.
        method: Unbound asynchronous generator method.
        close_on_complete: Whether to close the backend stream at normal completion.
        summary: Short description, or ``None`` to use the first docstring paragraph.
        description: Detailed description, or ``None`` to use the full docstring.
        tags: Immutable documentation tags.
        deprecated: Whether the action is deprecated in documentation.

    Attributes:
        channel: Registered channel route.
        close_on_complete: Whether normal completion closes the subscription stream.
        output_model: Resolved model used to validate each event after configuration.
    """

    output_model: TypeForm[Any]

    def __init__(
        self,
        channel: str,
        *,
        method: Callable[..., Any],
        close_on_complete: bool = True,
        summary: str | None = None,
        description: str | None = None,
        tags: frozenset[str] | None = None,
        deprecated: bool = False,
    ) -> None:
        super().__init__(method=method, summary=summary, description=description, tags=tags, deprecated=deprecated)
        self.channel = channel
        self.close_on_complete = close_on_complete

    @override
    def _configure(
        self,
        owner: type,
        method_name: str,
        backend_class: type[SerializationBackend],
    ) -> StreamAction:
        if self._backend_class is not None:
            msg = "Stream action is already configured"
            raise RuntimeError(msg)

        if not inspect.isasyncgenfunction(self.method):
            msg = f"{owner.__qualname__}.{method_name} must be an async generator"
            raise ImproperlyConfigured(msg)

        data_annotation, return_annotation = self._inspect_method_signature(owner, method_name)

        if get_origin(return_annotation) not in (AsyncIterator, AsyncGenerator):
            msg = f"{owner.__qualname__}.{method_name} must return AsyncIterator[Model]"
            raise ImproperlyConfigured(msg)

        try:
            backend = backend_class()
        except Exception as exc:
            msg = f"Cannot instantiate backend for {owner.__qualname__}"
            raise ImproperlyConfigured(msg) from exc

        arguments = get_args(return_annotation)
        model = _output_model(arguments[0], backend) if arguments else None

        if model is None:
            msg = f"{owner.__qualname__}.{method_name} must yield a supported output model"
            raise ImproperlyConfigured(msg)

        action = StreamAction(
            self.channel,
            method=self.method,
            close_on_complete=self.close_on_complete,
            summary=self.summary,
            description=self.description,
            tags=self.tags,
            deprecated=self.deprecated,
        )

        action.method_name = method_name
        action._backend_class = backend_class
        action.data_annotation = data_annotation
        action.return_annotation = return_annotation
        action.output_model = model
        return action

    async def __call__(
        self,
        data: Any,
        context: SubscribeContext,
        *,
        consumer: Any,
    ) -> AsyncGenerator[Any, None]:
        """Yield validated JSON-compatible events for an accepted subscription.

        The caller owns the consumer and must close the returned generator.
        Input data must already have been validated for ``on_subscribe``.

        Args:
            data: Validated subscription data.
            context: The context passed to ``on_subscribe``.
            consumer: Consumer instance managed by the caller.

        Yields:
            JSON-compatible events validated against the stream output model.

        Raises:
            RuntimeError: If the action has not been configured.
            Exception: If the handler or output validation fails.
        """
        if self._backend_class is None:
            msg = "Stream action is not configured"
            raise RuntimeError(msg)

        backend = self._backend_class()
        async with aclosing(self.method(consumer, data=data, context=context)) as generator:
            async for item in generator:
                yield _validate_output(backend, self.output_model, item)
