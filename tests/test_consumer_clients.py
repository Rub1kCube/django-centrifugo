import asyncio
from typing import override

import cent
import grpc
import httpx2
import msgspec
import pytest
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.test import override_settings

from django_centrifugo._proto import proxy_pb2, proxy_pb2_grpc
from django_centrifugo.consumers import Consumer
from django_centrifugo.consumers.decorators import rpc
from django_centrifugo.contracts import RpcContext, SubscribeContext
from django_centrifugo.grpc.server import create_server
from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend


CLIENT_OPTIONS = {"api_endpoint": "https://centrifugo.example.com/api", "api_key": "test-api-key"}
METADATA = (("x-centrifugo-proxy-key", "test-proxy-key"),)


class Message(msgspec.Struct):
    text: str


def test_consumer_client_is_lazy_optional_and_unavailable_after_cleanup() -> None:
    async def run() -> None:
        consumer = Consumer[MsgspecSerializationBackend]()
        with override_settings(CENTRIFUGO_SETTINGS={}):
            assert consumer._centrifugo_client is None
            with pytest.raises(ImproperlyConfigured, match="must be configured"):
                _ = consumer.centrifugo
            await consumer._close_centrifugo_client()
            with pytest.raises(RuntimeError, match="already closed"):
                _ = consumer.centrifugo

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_rpc_closes_native_consumer_client(outcome: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        clients: list[cent.AsyncClient] = []
        started = asyncio.Event()
        closed = asyncio.Event()

        async def respond(_: httpx2.Request) -> httpx2.Response:
            started.set()
            if outcome == "cancel":
                await asyncio.get_running_loop().create_future()
            if outcome == "error":
                return httpx2.Response(200, json={"error": {"code": 100, "message": "unavailable"}})
            return httpx2.Response(200, json={"result": {}})

        class PublishingConsumer(Consumer[MsgspecSerializationBackend]):
            @rpc(f"pycent:rpc.{outcome}")
            async def send(self, data: Message, context: RpcContext) -> None:
                client = self.centrifugo
                clients.append(client)
                assert type(client) is cent.AsyncClient
                assert self.centrifugo is client
                await client.publish(channel="chat", data={"text": data.text})

            @override
            async def _close_centrifugo_client(self) -> None:
                try:
                    await super()._close_centrifugo_client()
                finally:
                    closed.set()

        consumer_path = f"{__name__}.PublishingConsumer"
        monkeypatch.setattr(consumer_path, PublishingConsumer, raising=False)
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            with override_settings(
                CENTRIFUGO_SETTINGS={
                    "proxy_key": "test-proxy-key",
                    "consumers": [consumer_path],
                    "client": {**CLIENT_OPTIONS, "http_client": http},
                }
            ):
                server = create_server("127.0.0.1:0")
                await server.start()
                try:
                    async with grpc.aio.insecure_channel(server.address) as channel:
                        stub = proxy_pb2_grpc.CentrifugoProxyStub(channel)  # type: ignore[no-untyped-call]
                        call = stub.RPC(
                            proxy_pb2.RPCRequest(
                                method=f"pycent:rpc.{outcome}",
                                encoding="json",
                                data=b'{"text":"hi"}',
                            ),
                            metadata=METADATA,
                            timeout=5,
                        )
                        if outcome == "cancel":
                            await asyncio.wait_for(started.wait(), 2)
                            call.cancel()
                            with pytest.raises(asyncio.CancelledError):
                                await call
                        else:
                            reply = await call
                            assert reply.HasField("error") == (outcome == "error")
                        await asyncio.wait_for(closed.wait(), 2)
                finally:
                    await server.stop(None)
                assert len(clients) == 1
                with pytest.raises(cent.ClosedError):
                    await clients[0].info()
            assert not http.is_closed

    asyncio.run(run())


@pytest.mark.parametrize("accepted", [False, True])
def test_subscription_keeps_client_through_end_hook_and_closes_it(
    accepted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        clients: list[cent.AsyncClient] = []
        closed = asyncio.Event()
        end_hook_ran = asyncio.Event()
        route = f"pycent:subscription.{accepted}"

        class PublishingConsumer(Consumer[MsgspecSerializationBackend]):
            channel = route

            @override
            async def on_subscribe(self, data: None, context: SubscribeContext) -> None:
                clients.append(self.centrifugo)
                await self.centrifugo.publish(channel="chat", data={"text": "subscribed"})
                if not accepted:
                    raise PermissionDenied

            @override
            async def on_stream_end(self, context: SubscribeContext) -> None:
                assert self.centrifugo is clients[0]
                await self.centrifugo.publish(channel="chat", data={"text": "ended"})
                end_hook_ran.set()

            @override
            async def _close_centrifugo_client(self) -> None:
                try:
                    await super()._close_centrifugo_client()
                finally:
                    closed.set()

        consumer_path = f"{__name__}.PublishingConsumer"
        monkeypatch.setattr(consumer_path, PublishingConsumer, raising=False)
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda _: httpx2.Response(200, json={"result": {}}),
            )
        ) as http:
            with override_settings(
                CENTRIFUGO_SETTINGS={
                    "proxy_key": "test-proxy-key",
                    "consumers": [consumer_path],
                    "client": {**CLIENT_OPTIONS, "http_client": http},
                }
            ):
                server = create_server("127.0.0.1:0")
                await server.start()
                try:
                    async with grpc.aio.insecure_channel(server.address) as channel:
                        stub = proxy_pb2_grpc.CentrifugoProxyStub(channel)  # type: ignore[no-untyped-call]
                        call = stub.SubscribeUnidirectional(
                            proxy_pb2.SubscribeRequest(
                                channel=route,
                                encoding="json",
                            ),
                            metadata=METADATA,
                            timeout=5,
                        )
                        reply = await call.read()
                        assert reply.subscribe_response.HasField("error") == (not accepted)
                        if accepted:
                            call.cancel()
                        await asyncio.wait_for(closed.wait(), 2)
                finally:
                    await server.stop(None)
                assert end_hook_ran.is_set() == accepted
                assert len(clients) == 1
                with pytest.raises(cent.ClosedError):
                    await clients[0].info()

    asyncio.run(run())
