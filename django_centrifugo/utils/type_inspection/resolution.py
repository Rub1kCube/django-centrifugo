from collections.abc import Mapping
from functools import reduce
from operator import or_
from types import get_original_bases
from typing import Annotated, Any, TypeAliasType, TypeVar, get_args, get_origin

from django_centrifugo.utils.type_inspection.predicates import (
    is_annotated,
    is_literal,
    is_none_type,
    is_type_alias,
    is_type_var,
    is_union,
)


def resolve_type(
    annotation: Any,
    bindings: Mapping[Any, Any],
) -> Any:
    """Выбрать способ подстановки параметров для соответствующего вида аннотации."""
    if is_type_var(annotation):
        return resolve_type_var(annotation, bindings)

    origin = get_origin(annotation)
    alias = origin or annotation

    if is_type_alias(alias):
        return resolve_type_alias(alias, get_args(annotation), bindings)

    if is_annotated(annotation):
        return resolve_annotated(annotation, bindings)

    if is_union(annotation):
        return resolve_union(annotation, bindings)

    if is_literal(annotation):
        return annotation

    return resolve_generic(annotation, bindings)


def resolve_type_var(
    parameter: TypeVar,
    bindings: Mapping[Any, Any],
) -> Any:
    """Подставить тип по цепочке привязок, сохранив непривязанный параметр."""
    replacement = bindings.get(parameter, parameter)
    return parameter if replacement is parameter else resolve_type(replacement, bindings)


def resolve_type_alias(
    alias: TypeAliasType,
    arguments: tuple[Any, ...],
    bindings: Mapping[Any, Any],
) -> Any:
    """Раскрыть alias с учётом его собственных параметров и внешних привязок."""
    parameters = dict(zip(alias.__type_params__, arguments, strict=False))
    return resolve_type(alias.__value__, {**bindings, **parameters})


def resolve_annotated(
    annotation: Any,
    bindings: Mapping[Any, Any],
) -> Any:
    """Разрешить базовый тип Annotated, сохранив метаданные и их порядок."""
    model, metadata = unwrap_annotation(annotation)
    return Annotated[resolve_type(model, bindings), *metadata]


def resolve_union(
    annotation: Any,
    bindings: Mapping[Any, Any],
) -> Any:
    """Разрешить все варианты объединения, включая NoneType."""
    return reduce(or_, (resolve_type(item, bindings) for item in get_args(annotation)))


def resolve_generic(
    annotation: Any,
    bindings: Mapping[Any, Any],
) -> Any:
    """Подставить аргументы generic-типа, сохранив исходную аннотацию при отсутствии изменений."""
    origin = get_origin(annotation)
    arguments = get_args(annotation) if origin else getattr(annotation, "__parameters__", ())

    if not arguments:
        return annotation
    resolved = tuple(resolve_type(value, bindings) for value in arguments)

    if resolved == arguments:
        return annotation
    return (origin or annotation)[resolved[0] if len(resolved) == 1 else resolved]


def unwrap_annotation(annotation: Any) -> tuple[Any, tuple[Any, ...]]:
    """Отделить метаданные Annotated, сохранив значимые значения, включая None."""
    if is_annotated(annotation):
        model, *metadata = get_args(annotation)
        return model, tuple(metadata)
    return annotation, ()


def model_annotation(annotation: Any) -> tuple[Any, bool]:
    """Отделить допустимость None, сохранив объединения моделей и метаданные их валидации."""
    model, metadata = unwrap_annotation(annotation)
    nullable = False
    if is_union(model):
        members = get_args(model)
        non_null = tuple(item for item in members if not is_none_type(item))
        if len(non_null) != len(members):
            model = reduce(or_, non_null)
            nullable = True
    return (Annotated[model, *metadata] if metadata else model), nullable


def generic_bindings(
    cls: type,
    owner: type,
    bindings: dict[Any, Any] | None = None,
) -> dict[Any, Any]:
    """Определить значения параметров типов по цепочке наследования до класса, определяющего метод."""
    bindings = bindings or {}
    if cls is owner:
        return bindings

    aliases = {get_origin(base) or base: base for base in get_original_bases(cls)}
    for base in cls.__bases__:
        if issubclass(base, owner):
            parameters = getattr(base, "__parameters__", getattr(base, "__type_params__", ()))
            arguments = get_args(aliases.get(base, base))
            resolved = {key: resolve_type(value, bindings) for key, value in zip(parameters, arguments, strict=False)}
            return generic_bindings(base, owner, bindings | resolved)
    return {}
