from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

from django.core.exceptions import ImproperlyConfigured

from django_centrifugo.actions.rpc import RpcAction


if TYPE_CHECKING:
    from django_centrifugo.serialization.base import SerializationBackend


FunctionT = TypeVar("FunctionT", bound=Callable[..., Any])


def rpc(
    name: str,
    *,
    backend_serializer: type[SerializationBackend] | None = None,
    summary: str | None = None,
    description: str | None = None,
    tags: frozenset[str] | None = None,
    deprecated: bool = False,
) -> Callable[[FunctionT], FunctionT]:
    """Declare a consumer method as an RPC action.

    The method is registered when its containing consumer is loaded from
    ``CENTRIFUGO_SETTINGS['consumers']``. The
    method must be asynchronous, accept annotated ``data`` and ``context``
    keyword arguments, and annotate the return with a backend-supported model,
    :data:`~django_centrifugo.types.Output` of that model, or ``None``.
    The callable's public signature is checked, so an injection decorator may
    supply other arguments and expose an appropriate ``__signature__``.

    Args:
        name: Nonempty RPC method name. It must be unique within the consumer;
            the resulting name must also be globally unique.
        backend_serializer: Optional backend class for this action's payload
            validation and result serialization. Defaults to the consumer's backend.
        summary: Short description. Defaults to the first docstring paragraph.
        description: Detailed description. Defaults to the full method docstring.
        tags: Documentation tags; copied into an immutable tuple.
        deprecated: Whether the action is deprecated in documentation.

    Returns:
        A decorator creating an action descriptor. Access through a consumer
        instance binds the original method for ordinary direct calls.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If the name, backend
            override, or documentation metadata is invalid.
    """
    if not isinstance(cast("Any", name), str) or not name:
        msg = "RPC name must be a nonempty string"
        raise ImproperlyConfigured(msg)

    if backend_serializer is not None and not isinstance(cast("Any", backend_serializer), type):
        msg = "backend_serializer must be a serialization backend class"
        raise ImproperlyConfigured(msg)

    def decorate(method: FunctionT) -> FunctionT:
        return cast(
            "FunctionT",
            RpcAction(
                name,
                method=method,
                backend_serializer=backend_serializer,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
            ),
        )

    return decorate
