from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, Any, get_type_hints

from typing_extensions import TypeForm

from django_centrifugo.utils.type_inspection.resolution import generic_bindings, resolve_type


if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping


@dataclass(frozen=True)
class MethodSignature:
    """A method's signature, resolved annotations, and generic type bindings.

    The callable's public signature, including an explicit ``__signature__``,
    determines its parameters and annotations. Wrapped functions are used to
    resolve inherited type parameters and the names in copied annotations.
    An overriding method defines its own signature; annotations are not merged
    with those of other implementations in the method resolution order.
    """

    signature: inspect.Signature
    """Public callable signature, including default values."""

    annotations: Mapping[str, TypeForm[Any]]
    """Selected annotations with generic type parameters resolved."""

    bindings: Mapping[Any, TypeForm[Any]]
    """Generic type bindings between the target and declaring classes."""

    @classmethod
    def from_method(
        cls,
        method: Callable[..., Any],
        target_class: type | None = None,
        *,
        annotation_names: Collection[str] | None = None,
    ) -> "MethodSignature":
        """Inspect a function or method without retaining an instance bound to it.

        Without a target class, class-local names and inherited generic bindings
        are not available. The shared cache stores the callable and target class,
        without retaining a bound instance. A wrapper's public signature can
        differ from the wrapped function's signature.

        Args:
            method: Function or bound or unbound method to inspect.
            target_class: Optional class whose inheritance and namespace resolve
                the method's types.
            annotation_names: Names to resolve, or ``None`` to resolve every annotation.

        Returns:
            The signature and selected resolved annotations.

        Raises:
            NameError: If a selected annotation cannot be resolved.

        """
        function = getattr(method, "__func__", method)
        names = None if annotation_names is None else frozenset(annotation_names)
        return cls._parse(target_class, function, names)

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached signatures after changes to annotations, defaults, or namespaces."""
        cls._parse.cache_clear()

    @classmethod
    @lru_cache(maxsize=1024)
    def _parse(
        cls, target_class: type | None, function: Any, annotation_names: frozenset[str] | None
    ) -> MethodSignature:
        """Resolve the public signature and its selected annotations for the shared cache."""
        public_signature = inspect.signature(function)
        original = inspect.unwrap(function)
        original_signature = inspect.signature(original)
        namespace: dict[str, Any] = {}
        bindings: dict[Any, TypeForm[Any]] = {}

        if target_class is not None:
            owner = next(
                (
                    base
                    for base in reversed(target_class.__mro__)
                    if any(
                        inspect.unwrap(value.__func__ if isinstance(value, (staticmethod, classmethod)) else value)
                        is original
                        for value in vars(base).values()
                        if inspect.isfunction(value)
                        or isinstance(value, (staticmethod, classmethod))
                        or (callable(value) and hasattr(value, "__wrapped__"))
                    )
                ),
                target_class,
            )
            namespace.update({parameter.__name__: parameter for parameter in getattr(owner, "__type_params__", ())})
            namespace.update(
                {name: value for base in reversed(target_class.__mro__) for name, value in vars(base).items()}
            )
            namespace.update({base.__name__: base for base in target_class.__mro__})
            bindings = generic_bindings(target_class, owner)

        namespace.update({parameter.__name__: parameter for parameter in getattr(original, "__type_params__", ())})
        annotations = {
            name: parameter.annotation
            for name, parameter in public_signature.parameters.items()
            if parameter.annotation is not inspect.Signature.empty
        }
        if public_signature.return_annotation is not inspect.Signature.empty:
            annotations["return"] = public_signature.return_annotation

        original_annotations = {name: parameter.annotation for name, parameter in original_signature.parameters.items()}
        original_annotations["return"] = original_signature.return_annotation
        resolved = {}
        for name, annotation in annotations.items():
            if annotation_names is not None and name not in annotation_names:
                continue

            # Copies of the original annotations retain the original module's
            # names even when a wrapper lives in a different module.
            source = original if annotation == original_annotations.get(name, inspect.Signature.empty) else function
            module = sys.modules.get(getattr(source, "__module__", ""))
            globalns = dict(vars(module)) if module is not None else {}
            globalns.update(getattr(source, "__globals__", {}))
            try:
                resolved[name] = get_type_hints(
                    SimpleNamespace(__annotations__={name: annotation}),
                    globalns=globalns,
                    localns=namespace,
                    include_extras=True,
                )[name]
            except NameError as exc:
                msg = f"Cannot resolve annotation {name!r} on {getattr(function, '__qualname__', function)!s}: {exc}"
                raise NameError(msg) from exc
        return cls(
            public_signature,
            MappingProxyType({name: resolve_type(value, bindings) for name, value in resolved.items()}),
            MappingProxyType(bindings),
        )
