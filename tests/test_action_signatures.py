from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_centrifugo.actions.rpc import RpcAction
from django_centrifugo.actions.stream import StreamAction
from django_centrifugo.serialization.base import SerializationBackend


class Handlers[T]:
    async def rpc(self, data: T, context: object) -> T:
        return data

    async def stream(self, data: T, context: object) -> AsyncIterator[T]:
        yield data

    async def invalid_rpc(self, data: T, context: object, /) -> T:
        return data

    async def invalid_stream(self, data: T, context: object, /) -> AsyncIterator[T]:
        yield data


class ConcreteHandlers(Handlers[str]):
    pass


@pytest.mark.parametrize("kind", ["rpc", "stream"])
def test_actions_resolve_inherited_generic_signature(kind: str) -> None:
    backend = cast("type[SerializationBackend]", MagicMock())
    if kind == "rpc":
        action: Any = RpcAction("test", method=Handlers.rpc)._configure(ConcreteHandlers, "rpc", backend)
        expected_return: object = str
    else:
        action = StreamAction("test", method=Handlers.stream)._configure(ConcreteHandlers, "stream", backend)
        expected_return = AsyncIterator[str]

    assert action.data_annotation is str
    assert action.return_annotation == expected_return
    assert action.output_model is str


@pytest.mark.parametrize("kind", ["rpc", "stream"])
def test_actions_reject_signatures_that_cannot_accept_keyword_arguments(kind: str) -> None:
    backend = cast("type[SerializationBackend]", MagicMock())
    with pytest.raises(ImproperlyConfigured, match="must accept annotated data and context"):
        if kind == "rpc":
            RpcAction("test", method=Handlers.invalid_rpc)._configure(ConcreteHandlers, "invalid_rpc", backend)
        else:
            StreamAction("test", method=Handlers.invalid_stream)._configure(ConcreteHandlers, "invalid_stream", backend)
