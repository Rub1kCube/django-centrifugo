import asyncio
from io import StringIO
from unittest.mock import patch

import cent
import httpx2
import pytest
from django.core.management.base import CommandError
from django.test import override_settings
from rich.console import Console

from django_centrifugo.clients import create_async_client
from django_centrifugo.management.commands._startup_info import _startup_info, _StartupInfo


CLIENT_OPTIONS = {"api_endpoint": "https://centrifugo.example.com/api", "api_key": "test-api-key"}


def test_startup_check_can_be_skipped() -> None:
    with override_settings(CENTRIFUGO_SETTINGS={}):
        assert asyncio.run(_startup_info()) is None


@pytest.mark.parametrize("failed", [False, True])
def test_startup_check_uses_native_info_and_closes_client(failed: bool) -> None:
    async def run() -> None:
        def respond(request: httpx2.Request) -> httpx2.Response:
            assert str(request.url) == f"{CLIENT_OPTIONS['api_endpoint']}/info"
            if failed:
                return httpx2.Response(503, text="temporarily unavailable")
            return httpx2.Response(
                200,
                json={
                    "result": {
                        "nodes": [
                            {
                                "name": "node-1",
                                "version": "6.10.2",
                                "num_clients": 12,
                                "num_users": 8,
                                "num_channels": 3,
                                "uptime": 42,
                            }
                        ]
                    }
                },
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            with override_settings(CENTRIFUGO_SETTINGS={"client": {**CLIENT_OPTIONS, "http_client": http}}):
                client = create_async_client()
                with patch(
                    "django_centrifugo.management.commands._startup_info.create_async_client", return_value=client
                ):
                    if failed:
                        with pytest.raises(CommandError, match="Centrifugo startup check failed") as caught:
                            await _startup_info()
                        assert isinstance(caught.value.__cause__, cent.HTTPError)
                    else:
                        info = await _startup_info()
                        assert isinstance(info, cent.InfoResult)
                        assert info.nodes[0].num_clients == 12
                        startup = _StartupInfo(
                            address="127.0.0.1:10000",
                            pid=1,
                            maximum_concurrent_rpcs=None,
                            reload=False,
                            shutdown_grace=5,
                            stream_cleanup_timeout=5,
                            health_address=None,
                            centrifugo_url=CLIENT_OPTIONS["api_endpoint"],
                            centrifugo_info=info,
                        )
                        output = StringIO()
                        console = Console(file=output, width=140)
                        settings, nodes = startup.tables()
                        console.print(settings)
                        assert nodes is not None
                        console.print(nodes)
                        assert "node-1" in output.getvalue()
                        assert "6.10.2" in output.getvalue()
                        assert "42s" in output.getvalue()
                with pytest.raises(cent.ClosedError):
                    await client.info()

    asyncio.run(run())
