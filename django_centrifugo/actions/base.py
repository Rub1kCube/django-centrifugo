from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from functools import update_wrapper
from types import MethodType
from typing import TYPE_CHECKING, Any, Self, cast, overload

from django.core.exceptions import ImproperlyConfigured

from django_centrifugo.utils.type_inspection import MethodSignature


if TYPE_CHECKING:
    from collections.abc import Callable

    from django_centrifugo.serialization.base import SerializationBackend


class BaseAction(ABC):
    """Shared declaration state and registration contract for consumer actions.

    Actions act as descriptors: access through a consumer instance binds the
    original method. RPC and stream declarations are discovered together and
    configured through a common contract when the consumer registry is built.
    Each build creates separate actions for dispatch, leaving declarations unchanged.

    Args:
        method: Unbound consumer method.
        summary: Short description, or ``None`` to use the first docstring paragraph.
        description: Detailed description, or ``None`` to use the full docstring.
        tags: Immutable documentation tags.
        deprecated: Whether the action is deprecated in documentation.

    Attributes:
        method: Original unbound consumer method.
        method_name: Attribute name on the concrete consumer.
        data_annotation: Resolved input annotation after configuration.
        return_annotation: Resolved return annotation after configuration.
        summary: Short documentation description, if available.
        description: Detailed documentation description, if available.
        tags: Immutable documentation tags.
        deprecated: Whether the action is deprecated in documentation.
    """

    data_annotation: Any
    return_annotation: Any

    def __init__(
        self,
        *,
        method: Callable[..., Any],
        # AsyncAPI properties
        summary: str | None = None,
        description: str | None = None,
        tags: frozenset[str] | None = None,
        deprecated: bool = False,
    ) -> None:
        self.method_name = method.__name__
        self.method = method
        update_wrapper(cast("Any", self), method, updated=())
        self._backend_class: type[SerializationBackend] | None = None

        docstring = inspect.getdoc(method) or ""
        doc_summary, _, _ = docstring.partition("\n\n")
        self.summary = summary if summary is not None else doc_summary or None
        self.description = description if description is not None else docstring or None
        self.tags = tags
        self.deprecated = deprecated

    @abstractmethod
    def _configure(
        self,
        owner: type,
        method_name: str,
        backend_class: type[SerializationBackend],
    ) -> BaseAction:
        """Create a configured copy for the selected consumer and backend."""
        ...

    def _inspect_method_signature(self, owner: type, method_name: str) -> tuple[Any, Any]:
        try:
            signature = MethodSignature.from_method(
                self.method, target_class=owner, annotation_names={"data", "return"}
            )
            signature.signature.bind(None, data=None, context=None)
            return signature.annotations["data"], signature.annotations["return"]
        except (KeyError, TypeError, NameError) as exc:
            msg = (
                f"{owner.__qualname__}.{method_name} must accept annotated data and context "
                f"and annotate its return: {exc}"
            )
            raise ImproperlyConfigured(msg) from exc

    @overload
    def __get__(self, instance: None, owner: type | None = None) -> Self: ...

    @overload
    def __get__(self, instance: object, owner: type | None = None) -> Callable[..., Any]: ...

    def __get__(self, instance: object | None, owner: type | None = None) -> Self | Callable[..., Any]:
        if instance is None:
            return self
        return MethodType(self.method, instance)
