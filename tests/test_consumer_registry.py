import asyncio
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, ClassVar, TypeVar, override
from unittest.mock import Mock

import grpc
import msgspec
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_centrifugo._proto import proxy_pb2, proxy_pb2_grpc
from django_centrifugo.actions import UnknownActionError, resolve_action
from django_centrifugo.consumers import Consumer, registry as registry_module, resolve_stream, rpc, stream
from django_centrifugo.consumers.registry import _build_registry, _get_registry
from django_centrifugo.contracts import RpcContext, SubscribeContext
from django_centrifugo.grpc.server import create_server
from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend
from django_centrifugo.serialization.base import SerializationBackend
from django_centrifugo.settings import Settings, resolve_setting
from django_centrifugo.settings.resolver import clear_settings_cache


class Payload(msgspec.Struct):
    value: int


class BaseConsumer(Consumer[MsgspecSerializationBackend]):
    @rpc("echo")
    async def echo(self, data: Payload, context: RpcContext) -> Payload:
        return data


class SelectedConsumer(BaseConsumer):
    namespace = "selected"
    channel = "chat:room.<int:room_id>"
    channels: ClassVar[Sequence[str]] = ("chat:notice",)

    @override
    async def on_subscribe(self, data: Payload, context: SubscribeContext) -> dict[str, Any]:
        return {"params": context.params, "value": data.value}

    @stream("chat:room.<int:room_id>")
    async def events(self, data: Payload, context: SubscribeContext) -> AsyncIterator[Payload]:
        yield Payload(value=data.value + context.params["room_id"])


class OtherConsumer(BaseConsumer):
    namespace = "other"


class OverrideConsumer(BaseConsumer):
    namespace = "overridden"

    @override
    @rpc("replacement")
    async def echo(self, data: Payload, context: RpcContext) -> Payload:
        return Payload(value=data.value + 1)


class AbstractConsumer(Consumer[MsgspecSerializationBackend], ABC):
    @abstractmethod
    def dependency(self) -> None: ...


BackendT = TypeVar("BackendT", bound=SerializationBackend)


class GenericConsumer(Consumer[BackendT]):
    pass


def _path(cls: type[Any]) -> str:
    return f"{cls.__module__}.{cls.__name__}"


def test_only_configured_classes_are_registered_and_descriptors_stay_unchanged() -> None:
    paths = (_path(SelectedConsumer),)
    declaration = vars(BaseConsumer)["echo"]
    first = _build_registry(paths)
    second = _build_registry(paths)
    action, consumer = first.resolve_action("selected.echo")
    assert consumer is SelectedConsumer
    assert action is not declaration
    assert action is not second.resolve_action("selected.echo")[0]
    assert vars(BaseConsumer)["echo"] is declaration
    assert declaration.name == "echo"
    with pytest.raises(UnknownActionError):
        first.resolve_action("echo")
    with pytest.raises(UnknownActionError):
        first.resolve_action("other.echo")
    assert _build_registry(()).channels == ()
    assert not _build_registry(()).rpc_actions


def test_inheritance_respects_overridden_methods() -> None:
    registry = _build_registry((_path(OverrideConsumer),))
    action, consumer = registry.resolve_action("overridden.replacement")
    assert consumer is OverrideConsumer
    assert action.method is vars(OverrideConsumer)["echo"].method
    with pytest.raises(UnknownActionError):
        registry.resolve_action("overridden.echo")


@pytest.mark.parametrize("value", [None, "myapp.Consumer", {}, [None], [""], ["   "], [BaseConsumer]])
def test_consumer_settings_reject_invalid_collections(value: Any) -> None:
    with override_settings(CENTRIFUGO_SETTINGS={"consumers": value}):
        with pytest.raises(ImproperlyConfigured, match="nonempty consumer class paths"):
            resolve_setting(Settings.consumers)


@pytest.mark.parametrize("paths", [[], ()])
def test_empty_consumer_settings_are_valid(paths: Any) -> None:
    with override_settings(CENTRIFUGO_SETTINGS={"consumers": paths}):
        assert resolve_setting("consumers") == ()
        with pytest.raises(UnknownActionError):
            resolve_action("selected.echo")
        assert resolve_stream("chat:room.42") is None


def test_old_module_setting_has_migration_error() -> None:
    with override_settings(CENTRIFUGO_SETTINGS={"action_modules": [__name__]}):
        with pytest.raises(ImproperlyConfigured, match="has been removed; use 'consumers'"):
            resolve_setting("consumers")


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("missing_consumer_module.Consumer", "Cannot import configured consumer"),
        (f"{__name__}.MissingConsumer", "Cannot import configured consumer"),
        ("not_a_class_path", "Cannot import configured consumer"),
        (_path(Payload), "must be a Consumer subclass"),
        (_path(Consumer), "must be a concrete Consumer subclass"),
        (_path(AbstractConsumer), "must be a concrete Consumer subclass"),
        (_path(GenericConsumer), "must be a concrete Consumer subclass"),
    ],
)
def test_invalid_targets_fail_when_loading(path: str, message: str) -> None:
    with override_settings(CENTRIFUGO_SETTINGS={"consumers": [path]}):
        with pytest.raises(ImproperlyConfigured, match=message):
            resolve_action("anything")


def test_import_error_inside_consumer_module_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "broken_consumer_module.py").write_text("import missing_consumer_dependency\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ImproperlyConfigured, match="missing_consumer_dependency") as error:
        _build_registry(("broken_consumer_module.Consumer",))
    assert isinstance(error.value.__cause__, ImportError)


def test_duplicate_classes_including_aliases_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    alias_path = f"{__name__}.ConsumerAlias"
    monkeypatch.setattr(alias_path, SelectedConsumer, raising=False)
    for second_path in (_path(SelectedConsumer), alias_path):
        with pytest.raises(ImproperlyConfigured, match="configured more than once"):
            _build_registry((_path(SelectedConsumer), second_path))


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("namespace", 1, "namespace must be a string"),
        ("channel", None, "channel must be a string"),
        ("channels", "chat:room", "channels must be a sequence"),
        ("channels", [""], "channels must be a sequence"),
        ("channels", ["chat:room.<int:room_id>"], "duplicate channel patterns"),
        ("channel", "chat:<missing_converter:id>", "Invalid channel pattern"),
    ],
)
def test_declarations_are_validated_at_load_time(
    monkeypatch: pytest.MonkeyPatch, attribute: str, value: Any, message: str
) -> None:
    monkeypatch.setattr(SelectedConsumer, attribute, value)
    assert not _build_registry((_path(OtherConsumer),)).channels
    with pytest.raises(ImproperlyConfigured, match=message):
        _build_registry((_path(SelectedConsumer),))


def test_rpc_and_channel_conflicts_are_configuration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OtherConsumer, "namespace", "selected")
    with pytest.raises(ImproperlyConfigured, match=r"RPC action 'selected\.echo'.*SelectedConsumer and OtherConsumer"):
        _build_registry((_path(SelectedConsumer), _path(OtherConsumer)))
    monkeypatch.setattr(OtherConsumer, "namespace", "other")
    monkeypatch.setattr(OtherConsumer, "channel", SelectedConsumer.channel)
    with pytest.raises(ImproperlyConfigured, match=r"Channel pattern.*SelectedConsumer and OtherConsumer"):
        _build_registry((_path(SelectedConsumer), _path(OtherConsumer)))


def test_failed_build_is_not_published_or_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    alias_path = f"{__name__}.ConsumerAlias"
    monkeypatch.setattr(alias_path, SelectedConsumer, raising=False)
    with override_settings(CENTRIFUGO_SETTINGS={"consumers": [_path(SelectedConsumer), alias_path]}):
        with pytest.raises(ImproperlyConfigured, match="configured more than once"):
            resolve_action("selected.echo")
        monkeypatch.setattr(alias_path, OtherConsumer)
        assert resolve_action("selected.echo").name == "selected.echo"
        assert resolve_action("other.echo").name == "other.echo"


def test_cache_invalidation_preserves_previous_snapshot() -> None:
    with override_settings(CENTRIFUGO_SETTINGS={"consumers": [_path(SelectedConsumer)]}):
        original = _get_registry()
        assert _get_registry() is original
        assert resolve_stream("chat:room.42") is not None
        assert resolve_stream("chat:notice") is None
        clear_settings_cache()
        assert _get_registry() is not original
        with override_settings(CENTRIFUGO_SETTINGS={"consumers": (_path(OtherConsumer),)}):
            assert resolve_action("other.echo").name == "other.echo"
            with pytest.raises(UnknownActionError):
                resolve_action("selected.echo")
            assert resolve_stream("chat:room.42") is None
            assert original.resolve_action("selected.echo")[1] is SelectedConsumer
        assert resolve_action("selected.echo").name == "selected.echo"


def test_channel_match_contains_parameters_and_stream_without_recompiling(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _build_registry((_path(SelectedConsumer),))
    monkeypatch.setattr(registry_module, "RoutePattern", Mock(side_effect=AssertionError("unexpected compilation")))
    for _ in range(2):
        match = registry.resolve_channel("chat:room.42")
        assert match is not None
        entry, params = match
        assert params == {"room_id": 42}
        assert entry.consumer_class is SelectedConsumer
        action = entry.get_stream()
        assert action is not None
        assert action.channel == SelectedConsumer.channel
    assert registry.resolve_channel("chat:room.invalid") is None
    assert registry.resolve_channel("unknown") is None


def test_overlapping_literal_and_dynamic_routes_remain_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OtherConsumer, "channel", "chat:room.42")
    registry = _build_registry((_path(SelectedConsumer), _path(OtherConsumer)))
    with pytest.raises(ImproperlyConfigured, match="matches multiple channel patterns"):
        registry.resolve_channel("chat:room.42")


def test_invalid_configuration_fails_before_grpc_server_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = Mock(side_effect=AssertionError("server created before validating consumers"))
    monkeypatch.setattr(grpc.aio, "server", factory)
    with override_settings(CENTRIFUGO_SETTINGS={"proxy_key": "test-key", "consumers": ["missing.Class"]}):
        with pytest.raises(ImproperlyConfigured, match="Cannot import configured consumer"):
            create_server()
    factory.assert_not_called()


def test_grpc_dispatch_and_live_server_snapshot() -> None:
    async def run() -> None:
        metadata = (("x-centrifugo-proxy-key", "test-key"),)
        request = proxy_pb2.RPCRequest(method="selected.echo", encoding="json", data=b'{"value":7}')
        with override_settings(CENTRIFUGO_SETTINGS={"proxy_key": "test-key", "consumers": [_path(SelectedConsumer)]}):
            server = create_server("127.0.0.1:0")
            await server.start()
            try:
                async with grpc.aio.insecure_channel(server.address) as channel:
                    stub = proxy_pb2_grpc.CentrifugoProxyStub(channel)  # type: ignore[no-untyped-call]
                    reply = await stub.RPC(request, metadata=metadata, timeout=5)
                    assert msgspec.json.decode(reply.result.data) == {"value": 7}
                    subscription = proxy_pb2.SubscribeRequest(
                        channel="chat:room.42", encoding="json", data=b'{"value":7}'
                    )
                    accepted, event = [
                        message
                        async for message in stub.SubscribeUnidirectional(subscription, metadata=metadata, timeout=5)
                    ]
                    assert not accepted.subscribe_response.HasField("error")
                    assert msgspec.json.decode(accepted.subscribe_response.result.data) == {
                        "params": {"room_id": 42},
                        "value": 7,
                    }
                    assert msgspec.json.decode(event.publication.data) == {"value": 49}
                    subscription.data = b'{"value":"invalid"}'
                    rejected = [
                        message
                        async for message in stub.SubscribeUnidirectional(subscription, metadata=metadata, timeout=5)
                    ]
                    assert len(rejected) == 1
                    assert rejected[0].subscribe_response.HasField("error")
                    with override_settings(CENTRIFUGO_SETTINGS={"proxy_key": "test-key", "consumers": []}):
                        empty_server = create_server("127.0.0.1:0")
                        await empty_server.start()
                        try:
                            async with grpc.aio.insecure_channel(empty_server.address) as empty_channel:
                                empty_stub = proxy_pb2_grpc.CentrifugoProxyStub(empty_channel)  # type: ignore[no-untyped-call]
                                assert (await empty_stub.RPC(request, metadata=metadata, timeout=5)).HasField("error")
                                assert not (await stub.RPC(request, metadata=metadata, timeout=5)).HasField("error")
                        finally:
                            await empty_server.stop(None)
            finally:
                await server.stop(None)

    asyncio.run(run())


def test_single_file_quickstart_loads_consumers_from_main() -> None:
    root = Path(__file__).resolve().parents[1]
    code = (
        "from django_centrifugo.actions import resolve_action; "
        "from django_centrifugo.consumers import resolve_stream; "
        "assert resolve_action('greeting.hello').name == 'greeting.hello'; "
        "assert resolve_stream('chat:room.42') is not None"
    )
    result = subprocess.run(
        [sys.executable, str(root / "docs/examples/quickstart.py"), "shell", "--command", code],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
