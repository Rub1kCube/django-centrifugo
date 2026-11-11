from types import NoneType, UnionType
from typing import Annotated, Any, Literal, TypeAliasType, TypeGuard, TypeVar, Union, get_origin


def is_annotated(annotation: Any) -> bool:
    """Проверить, является ли внешняя аннотация Annotated."""
    return get_origin(annotation) is Annotated


def is_literal(annotation: Any) -> bool:
    """Проверить, задаёт ли аннотация набор значений Literal."""
    return get_origin(annotation) is Literal


def is_union(annotation: Any) -> bool:
    """Распознать объединение typing.Union или запись через оператор |."""
    return get_origin(annotation) in (Union, UnionType)


def is_none_type(annotation: Any) -> bool:
    """Проверить именно тип NoneType, а не значение None или nullable-объединение."""
    return annotation is NoneType


def is_type_var(annotation: Any) -> TypeGuard[TypeVar]:
    """Распознать параметр TypeVar и сузить его тип для анализатора."""
    return isinstance(annotation, TypeVar)


def is_type_alias(annotation: Any) -> TypeGuard[TypeAliasType]:
    """Распознать сам объект алиаса; у параметризованного алиаса сначала нужен get_origin."""
    return isinstance(annotation, TypeAliasType)


def is_safe_subclass[T](
    annotation: Any,
    class_or_tuple: type[T] | tuple[type[T], ...],
) -> TypeGuard[type[T]]:
    """Проверить наследование класса, возвращая False для экземпляров и неподдерживаемых типов."""
    if not isinstance(annotation, type):
        return False
    try:
        return issubclass(annotation, class_or_tuple)
    except TypeError:
        return False
