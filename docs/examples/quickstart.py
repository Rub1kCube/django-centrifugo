"""A single-file Django application with a Centrifugo RPC and stream."""

import asyncio
import logging
import secrets
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import override

import msgspec
from django.conf import settings
from django.core.management import execute_from_command_line
from django.http import HttpRequest, HttpResponse
from django.urls import path

from django_centrifugo.consumers import Consumer, rpc, stream
from django_centrifugo.contracts import RpcContext, SubscribeContext
from django_centrifugo.errors import ErrorContext, ProxyError
from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend


logger = logging.getLogger(__name__)

settings.configure(
    SECRET_KEY=secrets.token_urlsafe(32),
    DEBUG=True,
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["localhost", "127.0.0.1"],
    INSTALLED_APPS=["django_centrifugo"],
    CENTRIFUGO_SETTINGS={
        "proxy_key": "local-proxy-example-key",
        "consumers": [f"{__name__}.GreetingConsumer"],
        "client": {"api_endpoint": "http://127.0.0.1:8000/api", "api_key": "local-api-example-key"},
    },
)


class Greeting(msgspec.Struct):
    name: str


class GreetingResponse(msgspec.Struct):
    message: str


class Subscription(msgspec.Struct):
    language: str = "ru"


class RoomEvent(msgspec.Struct):
    room_id: int
    language: str
    sequence: int


class GreetingConsumer(Consumer[MsgspecSerializationBackend]):
    namespace = "greeting"
    channel = "chat:room.<int:room_id>"

    @override
    async def on_error(self, error: ErrorContext) -> ProxyError | None:
        if error.kind == "validation":
            return ProxyError(1400, "Invalid request data")
        if error.kind == "internal":
            logger.error("Centrifugo %s failed", error.endpoint, exc_info=error.exception)
            return ProxyError(1500, "An unexpected error occurred", temporary=True)
        return None

    @override
    async def on_subscribe(self, data: Subscription, context: SubscribeContext) -> dict[str, int | str]:
        return {"room_id": context.params["room_id"], "language": data.language}

    @rpc("hello")
    async def hello(self, data: Greeting, context: RpcContext) -> GreetingResponse:
        _ = context
        return GreetingResponse(message=f"Hello, {data.name}!")

    @stream("chat:room.<int:room_id>", close_on_complete=False)
    async def events(self, data: Subscription, context: SubscribeContext) -> AsyncIterator[RoomEvent]:
        for sequence in range(1, 6):
            if sequence > 1:
                await asyncio.sleep(2)
            yield RoomEvent(room_id=context.params["room_id"], language=data.language, sequence=sequence)


def index(_request: HttpRequest) -> HttpResponse:
    html = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
    return HttpResponse(html)


urlpatterns = [path("", index)]


if __name__ == "__main__":
    execute_from_command_line(sys.argv)
