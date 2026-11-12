from __future__ import annotations

import inspect
from types import NoneType
from typing import TYPE_CHECKING, Any, override

from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypeForm

from django_centrifugo.actions.base import BaseAction
from django_centrifugo.actions.errors import PayloadValidationError
from django_centrifugo.serialization.output import _output_model, _validate_output


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from django_centrifugo.contracts import RpcContext
    from django_centrifugo.serialization.base import SerializationBackend


class RpcAction(BaseAction):
    """An RPC declaration or a configured action.

    :func:`~django_centrifugo.consumers.decorators.rpc.rpc` creates an unbound action.
    The common consumer registration process configures a separate action for
    each RPC name, including the consumer namespace prefix. The caller
    supplies the instance on which the method is executed. The configured
    action validates its result against the declared model, or requires
    ``None`` when the method is annotated as returning no data.

    Args:
        name: Declared or registered RPC method name.
        method: Unbound asynchronous method to invoke.
        backend_serializer: Optional per-action backend override.
        summary: Explicit short description, or ``None`` to use the docstring.
        description: Explicit description, or ``None`` to use the docstring.
        tags: Documentation tags.
        deprecated: Whether the action is deprecated in documentation.

    Attributes:
        name: RPC method name.
        method_name: Name of the method on the consumer.
        method: Unbound method registered for the action.
        backend_serializer: Optional per-action backend override.
        data_annotation: Resolved input model annotation, available when configured.
        return_annotation: Resolved return annotation, available when configured.
        output_model: Resolved model used for output validation, or ``None``.
        summary: Short documentation summary, if available.
        description: Detailed documentation description, if available.
        tags: Immutable documentation tags.
        deprecated: Whether the action is deprecated in documentation.

    """

    output_model: TypeForm[Any] | None

    def __init__(
        self,
        name: str,
        *,
        method: Callable[..., Coroutine[Any, Any, Any]],
        backend_serializer: type[SerializationBackend] | None = None,
        summary: str | None = None,
        description: str | None = None,
        tags: frozenset[str] | None = None,
        deprecated: bool = False,
    ) -> None:
        super().__init__(
            method=method,
            summary=summary,
            description=description,
            tags=tags,
            deprecated=deprecated,
        )

        self.name = name
        self.backend_serializer = backend_serializer

    @override
    def _configure(
        self,
        owner: type,
        method_name: str,
        backend_class: type[SerializationBackend],
    ) -> RpcAction:
        if self._backend_class is not None:
            msg = "Action is already configured"
            raise RuntimeError(msg)

        backend_class = self.backend_serializer or backend_class
        if not inspect.iscoroutinefunction(self.method):
            msg = f"{owner.__qualname__}.{method_name} must be an async method"
            raise ImproperlyConfigured(msg)

        data_annotation, return_annotation = self._inspect_method_signature(owner, method_name)

        try:
            backend = backend_class()
        except Exception as exc:
            msg = f"Cannot instantiate backend for {owner.__qualname__}"
            raise ImproperlyConfigured(msg) from exc

        if not backend.is_supported_annotation(data_annotation):
            msg = f"Backend {backend_class.__qualname__} does not support {data_annotation!r}"
            raise ImproperlyConfigured(msg)

        output_model = _output_model(return_annotation, backend) if return_annotation is not NoneType else None
        if return_annotation is not NoneType and output_model is None:
            msg = f"{owner.__qualname__}.{method_name} must return a supported output model or None"
            raise ImproperlyConfigured(msg)

        namespace = getattr(owner, "namespace", "")
        name = f"{namespace}.{self.name}" if namespace else self.name
        action = RpcAction(
            name,
            method=self.method,
            backend_serializer=self.backend_serializer,
            summary=self.summary,
            description=self.description,
            tags=self.tags,
            deprecated=self.deprecated,
        )
        action.method_name = method_name
        action._backend_class = backend_class
        action.data_annotation = data_annotation
        action.return_annotation = return_annotation
        action.output_model = output_model
        return action

    async def __call__(
        self,
        data: dict[str, Any],
        context: RpcContext,
        *,
        consumer: Any,
    ) -> Any:
        """Validate and execute an RPC action, returning JSON-compatible values.

        The caller owns the consumer and its lifecycle.

        Args:
            data: JSON object supplied by the RPC client.
            context: Centrifugo connection and RPC fields.
            consumer: Consumer instance managed by the caller.

        Returns:
            JSON-compatible method result.

        Raises:
            PayloadValidationError: If the backend rejects the payload.
            RuntimeError: If the action has not been configured.
            TypeError: If the result does not satisfy a ``None`` return contract.
            Exception: If output model validation fails.
        """
        if self._backend_class is None:
            msg = "Action is not configured"
            raise RuntimeError(msg)

        backend = self._backend_class()
        try:
            model = backend.validate(self.data_annotation, data)
        except Exception as exc:
            raise PayloadValidationError(backend.format_validation_error(exc)) from exc

        result = await self.method(consumer, data=model, context=context)
        if self.output_model is not None:
            return _validate_output(backend, self.output_model, result)

        if result is not None:
            msg = "RPC annotated as None must return None"
            raise TypeError(msg)
        return None
