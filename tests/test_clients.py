import asyncio
from collections.abc import Callable

import cent
import httpx2
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_centrifugo.clients import create_async_client, create_client


CLIENT_OPTIONS = {"api_endpoint": "https://centrifugo.example.com/api", "api_key": "test-api-key"}


@pytest.mark.parametrize("factory", [create_client, create_async_client])
@pytest.mark.parametrize(
    "options",
    [
        None,
        [],
        "invalid",
        {1: "invalid"},
        {},
        {**CLIENT_OPTIONS, "unknown": True},
        {**CLIENT_OPTIONS, "api_endpoint": "invalid"},
        {**CLIENT_OPTIONS, "request_timeout": -1},
    ],
)
def test_factories_reject_missing_or_invalid_configuration(
    factory: Callable[[], cent.Client | cent.AsyncClient], options: object
) -> None:
    with override_settings(CENTRIFUGO_SETTINGS={"client": options}):
        with pytest.raises(ImproperlyConfigured, match="CENTRIFUGO_SETTINGS"):
            factory()


@pytest.mark.parametrize("factory", [create_client, create_async_client])
def test_factories_require_configuration(factory: Callable[[], cent.Client | cent.AsyncClient]) -> None:
    with override_settings(CENTRIFUGO_SETTINGS={}):
        with pytest.raises(ImproperlyConfigured, match="must be configured"):
            factory()


def test_native_sync_clients_use_updated_settings_and_are_independent() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"result": {}})

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
            with create_client() as first, create_client() as second:
                assert type(first) is cent.Client
                assert first is not second
                first.info()
                with override_settings(
                    CENTRIFUGO_SETTINGS={
                        "client": {
                            "api_endpoint": "https://another.example.com/custom/api",
                            "bearer_token_func": lambda: "test-token",
                            "http_client": http,
                        }
                    }
                ):
                    with create_client() as changed:
                        changed.info()
                second.info()
        assert not http.is_closed  # A caller-supplied HTTP client remains caller-owned.

    assert [str(request.url) for request in requests] == [
        "https://centrifugo.example.com/api/info",
        "https://another.example.com/custom/api/info",
        "https://centrifugo.example.com/api/info",
    ]
    assert requests[0].headers["X-API-Key"] == "test-api-key"
    assert requests[1].headers["Authorization"] == "Bearer test-token"


def test_native_async_client_factory_can_be_used_in_separate_event_loops() -> None:
    async def run() -> None:
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda _: httpx2.Response(200, json={"result": {}}),
            )
        ) as http:
            with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
                async with create_async_client() as client:
                    assert type(client) is cent.AsyncClient
                    assert await client.info() == cent.InfoResult()
            assert not http.is_closed

    asyncio.run(run())
    asyncio.run(run())
