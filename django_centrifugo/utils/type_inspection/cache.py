from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any

from typing_extensions import TypeForm


def cache_annotation[Result](function: Callable[[TypeForm[Any]], Result]) -> Callable[[TypeForm[Any]], Result]:
    """Кешировать аннотации, сохраняя поддержку нехешируемых метаданных Annotated."""

    @lru_cache
    def cached(key: tuple[TypeForm[Any], str]) -> Result:
        return function(key[0])

    @wraps(function)
    def wrapper(annotation: TypeForm[Any]) -> Result:
        try:
            hash(annotation)
        except TypeError:
            return function(annotation)

        return cached((annotation, repr(annotation)))

    return wrapper
