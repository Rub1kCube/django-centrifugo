import asyncio
import json
from unittest.mock import patch

import cent
import httpx2
import pytest
from django.test import override_settings

from django_centrifugo.clients import create_async_client, create_client
from django_centrifugo.shortcuts import apublish, publish


CLIENT_OPTIONS = {"api_endpoint": "https://centrifugo.example.com/api", "api_key": "test-api-key"}


def test_publish_sends_native_options_and_returns_pycent_result() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"result": {"offset": 42, "epoch": "test"}})

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
            client = create_client()
            with patch("django_centrifugo.shortcuts.create_client", return_value=client):
                result = publish(
                    "chat:1",
                    {"text": "Hello"},
                    idempotency_key="message-1",
                    skip_history=True,
                    tags={"kind": "chat"},
                    delta=True,
                    version=3,
                    version_epoch="messages",
                    timeout=0.5,
                )
            with pytest.raises(cent.ClosedError):
                client.info()
        assert not http.is_closed

    assert result == cent.PublishResult(offset=42, epoch="test")
    assert result.position() == cent.StreamPosition(offset=42, epoch="test")
    assert len(requests) == 1
    assert str(requests[0].url) == f"{CLIENT_OPTIONS['api_endpoint']}/publish"
    assert json.loads(requests[0].content) == {
        "channel": "chat:1",
        "data": {"text": "Hello"},
        "idempotency_key": "message-1",
        "skip_history": True,
        "tags": {"kind": "chat"},
        "delta": True,
        "version": 3,
        "version_epoch": "messages",
    }
    assert requests[0].extensions["timeout"]["read"] <= 0.5


def test_apublish_supports_binary_payload_and_closes_native_client() -> None:
    requests: list[httpx2.Request] = []

    async def run() -> cent.PublishResult:
        def respond(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            return httpx2.Response(200, json={"result": {"offset": 42, "epoch": "test"}})

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
                client = create_async_client()
                with patch("django_centrifugo.shortcuts.create_async_client", return_value=client):
                    result = await apublish("chat:1", b64data="aGk=", idempotency_key="binary-1", timeout=0.5)
                with pytest.raises(cent.ClosedError):
                    await client.info()
            assert not http.is_closed
        return result

    assert asyncio.run(run()) == cent.PublishResult(offset=42, epoch="test")
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"channel": "chat:1", "b64data": "aGk=", "idempotency_key": "binary-1"}
    assert requests[0].extensions["timeout"]["read"] <= 0.5


@pytest.mark.parametrize("asynchronous", [False, True])
def test_shortcuts_propagate_native_api_errors_without_retrying(asynchronous: bool) -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"error": {"code": 100, "message": "server unavailable", "temporary": True}})

    async def run() -> None:
        if asynchronous:
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
                with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
                    client = create_async_client()
                    with patch("django_centrifugo.shortcuts.create_async_client", return_value=client):
                        with pytest.raises(cent.ApiError, match="server unavailable") as caught:
                            await apublish("chat", {"text": "hi"})
                    with pytest.raises(cent.ClosedError):
                        await client.info()
        else:
            with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
                with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
                    sync_client = create_client()
                    with patch("django_centrifugo.shortcuts.create_client", return_value=sync_client):
                        with pytest.raises(cent.ApiError, match="server unavailable") as caught:
                            publish("chat", {"text": "hi"})
                    with pytest.raises(cent.ClosedError):
                        sync_client.info()
        assert caught.value.code == 100
        assert caught.value.temporary is True

    asyncio.run(run())
    assert len(requests) == 1


def test_apublish_closes_client_when_cancelled() -> None:
    async def run() -> None:
        started = asyncio.Event()

        async def respond(_: httpx2.Request) -> httpx2.Response:
            started.set()
            await asyncio.get_running_loop().create_future()
            raise AssertionError("cancelled request resumed")

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
                client = create_async_client()
                with patch("django_centrifugo.shortcuts.create_async_client", return_value=client):
                    task = asyncio.create_task(apublish("chat", {"text": "hi"}))
                    await asyncio.wait_for(started.wait(), 2)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 2)
                with pytest.raises(cent.ClosedError):
                    await client.info()

    asyncio.run(run())
