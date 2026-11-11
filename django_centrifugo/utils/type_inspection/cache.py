from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any


def cache_annotation[Result](function: Callable[[Any], Result]) -> Callable[[Any], Result]:
    """Кешировать аннотации, сохраняя поддержку нехешируемых метаданных Annotated."""

    @lru_cache
    def cached(key: tuple[Any, str]) -> Result:
        return function(key[0])

    @wraps(function)
    def wrapper(annotation: Any) -> Result:
        try:
            hash(annotation)
        except TypeError:
            return function(annotation)

        return cached((annotation, repr(annotation)))

    return wrapper
