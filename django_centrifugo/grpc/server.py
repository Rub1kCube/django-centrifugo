from __future__ import annotations

import asyncio
import logging
import math
import secrets
import sys
import time
from contextlib import aclosing, asynccontextmanager
from typing import TYPE_CHECKING, Any, cast, override

import grpc
import msgspec
from asgiref.sync import iscoroutinefunction, sync_to_async
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import close_old_connections
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from django_centrifugo._proto import proxy_pb2, proxy_pb2_grpc
from django_centrifugo.actions import PayloadValidationError, UnknownActionError
from django_centrifugo.consumers.consumer import _close_consumer_client
from django_centrifugo.consumers.registry import _get_registry
from django_centrifugo.contracts import RpcContext, SubscribeContext
from django_centrifugo.errors import (
    ErrorCode,
    InvalidRequestError,
    ProxyError,
    UnknownChannelError,
    default_error_handler,
)
from django_centrifugo.grpc._access_log import _log_access
from django_centrifugo.settings import Settings, resolve_setting


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from django_centrifugo.actions.stream import StreamAction
    from django_centrifugo.consumers.registry import _ConsumerRegistry
    from django_centrifugo.contracts import ClientProtocol, ClientTransport
    from django_centrifugo.serialization.base import SerializationBackend


logger = logging.getLogger(__name__)
_close_old_connections = sync_to_async(close_old_connections, thread_sensitive=True)


@asynccontextmanager
async def _database_scope() -> AsyncGenerator[None, None]:
    """Check connections in the thread used by Django's asynchronous ORM."""
    await _close_old_connections()
    try:
        yield
    finally:
        try:
            await _close_old_connections()
        except Exception:
            # Never replace a handler's exception or cancellation with cleanup failure.
            logger.exception("Centrifugo database connection cleanup failed")


def _json(data: bytes, *, default: Any = None) -> Any:
    if not data:
        return default
    try:
        return msgspec.json.decode(data)
    except msgspec.DecodeError as exc:
        msg = "Invalid JSON"
        raise InvalidRequestError(msg) from exc


def _encode_error_data(result: Any, backend_class: type[SerializationBackend] | None) -> bytes:
    backend = backend_class() if backend_class is not None else None

    def encode_model(value: Any) -> Any:
        if backend is not None and backend.is_supported_annotation(type(value)):
            return backend.to_python(value, mode="json", by_alias=True)
        msg = f"Unsupported domain error result: {type(value).__qualname__}"
        raise TypeError(msg)

    return msgspec.json.encode(result, enc_hook=encode_model)


async def _handle_error(error: Exception, consumer: Any = None) -> Any:
    if consumer is not None:
        try:
            return await consumer.on_error(error)
        except Exception as exc:  # noqa: BLE001 - raised errors delegate to the global handler
            error = exc

    try:
        handler = resolve_setting(Settings.error_handler)
        return (
            await handler(error)
            if iscoroutinefunction(handler)
            else await sync_to_async(handler, thread_sensitive=True)(error)
        )
    except Exception:
        logger.exception("Centrifugo proxy error handler failed")
        return ProxyError(ErrorCode.INTERNAL, "internal server error", temporary=True)


async def _error(
    error: Exception,
    consumer: Any = None,
    *,
    allow_data: bool = False,
    backend_class: type[SerializationBackend] | None = None,
) -> proxy_pb2.Error | bytes:
    try:
        result = await _handle_error(error, consumer)
        if not isinstance(result, ProxyError):
            if allow_data:
                return _encode_error_data(result, backend_class)
            logger.error("Centrifugo subscription error handler must return ProxyError")
            result = default_error_handler(error)

        if (
            not isinstance(cast("Any", result.code), int)
            or isinstance(result.code, bool)
            or (result.code not in ErrorCode and result.code not in range(400, 2000))
            or not isinstance(cast("Any", result.message), str)
            or not isinstance(cast("Any", result.temporary), bool)
        ):
            raise ValueError("Invalid proxy error")  # noqa: EM101, TRY003, TRY301

        return proxy_pb2.Error(code=result.code, message=result.message, temporary=result.temporary)
    except Exception:
        logger.exception("Centrifugo proxy error handler failed")
        return proxy_pb2.Error(code=ErrorCode.INTERNAL, message="internal server error", temporary=True)


class _ProxyService(proxy_pb2_grpc.CentrifugoProxyServicer):
    def __init__(self, registry: _ConsumerRegistry) -> None:
        self._registry = registry
        self.streams: set[asyncio.Task[Any]] = set()

    async def _finish_stream(self, consumer: Any, context: SubscribeContext, task: asyncio.Task[Any] | None) -> None:
        try:
            async with _database_scope():
                try:
                    await consumer.on_stream_end(context)
                except Exception as exc:
                    logger.exception("Centrifugo subscription stream cleanup failed")
                    await _handle_error(exc, consumer)
        except Exception:
            logger.exception("Centrifugo subscription database setup failed")
        finally:
            try:
                await _close_consumer_client(consumer)
            finally:
                if task is not None:
                    self.streams.discard(task)

    async def _authenticate(self, context: grpc.aio.ServicerContext[Any, Any]) -> None:
        values = [value for key, value in (context.invocation_metadata() or ()) if key == "x-centrifugo-proxy-key"]
        expected = resolve_setting(Settings.proxy_key)
        if (
            not expected
            or len(values) != 1
            or not isinstance(values[0], str)
            or not secrets.compare_digest(values[0].encode(), expected.encode())
        ):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid proxy credentials")

    @override
    async def RPC(
        self, request: proxy_pb2.RPCRequest, context: grpc.aio.ServicerContext[Any, Any]
    ) -> proxy_pb2.RPCResponse:
        started = time.monotonic()
        try:
            await self._authenticate(context)
        except grpc.aio.AbortError:
            _log_access("RPC", "", "UNAUTHENTICATED", started, grpc_status="UNAUTHENTICATED")
            raise
        except asyncio.CancelledError:
            _log_access("RPC", "", "CANCELLED", started, grpc_status="-")
            raise
        try:
            async with _database_scope():
                response = await self._rpc(request)
        except asyncio.CancelledError:
            _log_access("RPC", request.method, "CANCELLED", started, grpc_status="-")
            raise
        except Exception:
            logger.exception("Centrifugo RPC database setup failed")
            response = proxy_pb2.RPCResponse(
                error=proxy_pb2.Error(code=ErrorCode.INTERNAL, message="internal server error", temporary=True)
            )
        code = response.error.code if response.HasField("error") else None
        _log_access(
            "RPC", request.method, "ERROR" if code is not None else "OK", started, grpc_status="OK", error_code=code
        )
        return response

    async def _rpc(self, request: proxy_pb2.RPCRequest) -> proxy_pb2.RPCResponse:
        consumer = None
        backend_class = None

        try:
            try:
                if request.encoding != "json" or not request.method or request.b64data:
                    raise InvalidRequestError  # noqa: TRY301

                action, consumer_class = self._registry.resolve_action(request.method)
                backend_class = action._backend_class  # noqa: SLF001
                consumer = consumer_class()
                rpc_context = RpcContext(
                    client=request.client,
                    transport=cast("ClientTransport", request.transport),
                    protocol=cast("ClientProtocol", request.protocol),
                    encoding="json",
                    user=request.user,
                    method=request.method,
                    meta=_json(request.meta),
                    labels=dict(request.labels),
                )
                data = _json(request.data)

                if not isinstance(data, dict):
                    raise InvalidRequestError  # noqa: TRY301

                result = await action(data, rpc_context, consumer=consumer)
                return proxy_pb2.RPCResponse(result=proxy_pb2.RPCResult(data=msgspec.json.encode(result)))
            except Exception as exc:
                if not isinstance(
                    exc, (InvalidRequestError, UnknownActionError, PayloadValidationError, PermissionDenied)
                ):
                    logger.exception("Centrifugo RPC action failed")
                result = await _error(exc, consumer, allow_data=True, backend_class=backend_class)
                if isinstance(result, proxy_pb2.Error):
                    return proxy_pb2.RPCResponse(error=result)
                return proxy_pb2.RPCResponse(result=proxy_pb2.RPCResult(data=result))

        finally:
            await _close_consumer_client(consumer)

    @override
    async def SubscribeUnidirectional(  # noqa: C901, PLR0912, PLR0915
        self, request: proxy_pb2.SubscribeRequest, context: grpc.aio.ServicerContext[Any, Any]
    ) -> AsyncGenerator[proxy_pb2.StreamSubscribeResponse, None]:
        started = time.monotonic()
        try:
            await self._authenticate(context)
        except grpc.aio.AbortError:
            _log_access("SUBSCRIBE", "", "UNAUTHENTICATED", started, grpc_status="UNAUTHENTICATED")
            raise
        except asyncio.CancelledError:
            _log_access("SUBSCRIBE", "", "CANCELLED", started, grpc_status="-")
            raise

        consumer, sub_context, task = None, None, None
        declaration: StreamAction | None = None
        validated_data: Any = None
        accepted = False
        reported = False
        try:
            try:
                async with _database_scope():
                    consumer, sub_context, response, declaration, validated_data = await self._subscribe(request)
                    if consumer is not None and sub_context is not None:
                        task = asyncio.current_task()
                        if task is not None:
                            self.streams.add(task)
            except Exception:
                logger.exception("Centrifugo subscription database setup failed")
                response = proxy_pb2.SubscribeResponse(
                    error=proxy_pb2.Error(code=ErrorCode.INTERNAL, message="internal server error", temporary=True)
                )

            code = response.error.code if response.HasField("error") else None
            accepted = code is None
            _log_access(
                "SUBSCRIBE",
                request.channel,
                "ERROR" if code is not None else "ACCEPTED",
                started,
                grpc_status="-" if accepted else "OK",
                error_code=code,
            )
            reported = True
            yield proxy_pb2.StreamSubscribeResponse(subscribe_response=response)
            if consumer is not None and sub_context is not None:
                if declaration is not None:
                    generator = declaration(validated_data, sub_context, consumer=consumer)
                    try:
                        async with aclosing(generator):
                            while True:
                                try:
                                    async with _database_scope():
                                        output = await anext(generator)
                                        publication = msgspec.json.encode(output)
                                except StopAsyncIteration:
                                    break
                                yield proxy_pb2.StreamSubscribeResponse(
                                    publication=proxy_pb2.Publication(data=publication)
                                )
                    except Exception as exc:
                        logger.exception("Centrifugo subscription stream failed")
                        async with _database_scope():
                            await _handle_error(exc, consumer)
                        await context.abort(grpc.StatusCode.INTERNAL, "Subscription stream failed")
                    if declaration.close_on_complete:
                        return
                await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            if not reported:
                _log_access("SUBSCRIBE", request.channel, "CANCELLED", started, grpc_status="-")
            raise
        except Exception:
            if not reported:
                _log_access("SUBSCRIBE", request.channel, "ERROR", started, grpc_status="-")
            raise
        finally:
            try:
                if consumer is not None and sub_context is not None:
                    await self._finish_stream(consumer, sub_context, task)
            finally:
                if accepted:
                    _log_access("SUBSCRIBE", request.channel, "CLOSED", started, grpc_status="-")

    async def _subscribe(
        self, request: proxy_pb2.SubscribeRequest
    ) -> tuple[Any, SubscribeContext | None, proxy_pb2.SubscribeResponse, StreamAction | None, Any]:

        consumer = None
        sub_context = None
        accepted = False
        try:
            try:
                if request.encoding != "json" or not request.channel or request.b64data:
                    raise InvalidRequestError  # noqa: TRY301

                route = self._registry.resolve_channel(request.channel)
                if route is None:
                    raise UnknownChannelError  # noqa: TRY301

                entry, params = route
                consumer = entry.consumer_class()
                data = _json(request.data)
                if data is not None and not isinstance(data, dict):
                    raise InvalidRequestError  # noqa: TRY301

                sub_context = SubscribeContext(
                    client=request.client,
                    transport=cast("ClientTransport", request.transport),
                    protocol=cast("ClientProtocol", request.protocol),
                    encoding="json",
                    user=request.user,
                    channel=request.channel,
                    params=params,
                    meta=_json(request.meta),
                    token=request.token,
                    labels=dict(request.labels),
                )

                validated_data = entry.validate_data(data)
                result = cast("Any", await consumer.on_subscribe(data=validated_data, context=sub_context))
                if result is not None and not isinstance(result, dict):
                    msg = "on_subscribe must return a JSON object or None"
                    raise TypeError(msg)  # noqa: TRY301

                initial_data = msgspec.json.encode(result) if result is not None else b""

            except Exception as exc:
                if not isinstance(
                    exc, (PermissionDenied, InvalidRequestError, UnknownChannelError, PayloadValidationError)
                ):
                    logger.exception("Centrifugo subscription failed")
                error = cast("proxy_pb2.Error", await _error(exc, consumer))
            else:
                accepted = True
                return (
                    consumer,
                    sub_context,
                    proxy_pb2.SubscribeResponse(result=proxy_pb2.SubscribeResult(data=initial_data)),
                    entry.get_stream(),
                    validated_data,
                )
            return None, None, proxy_pb2.SubscribeResponse(error=error), None, None

        finally:
            if not accepted:
                await _close_consumer_client(consumer)


class GrpcProxyServer:
    """Manage a gRPC server and wait for stream cleanup during shutdown.

    Construct instances with :func:`create_server`.
    """

    def __init__(
        self,
        server: grpc.aio.Server,
        service: Any,
        *,
        address: str = "",
        bound_port: int = 0,
        health_server: grpc.aio.Server | None = None,
        health_servicer: Any = None,
        health_address: str | None = None,
        health_port: int | None = None,
        bind_on_start: bool = False,
    ) -> None:
        self._server = server
        self._service = service
        self.address = address
        """Requested proxy address; an ephemeral TCP port is resolved on startup."""
        self.bound_port = bound_port
        """Port returned by gRPC on startup, or zero before binding."""
        self.health_address = health_address
        """Health address, resolved on startup, or ``None`` when health is disabled."""
        self.health_port = health_port
        """Port returned by gRPC for health, or ``None`` before binding."""
        self._health_server = health_server
        self._health_servicer = health_servicer
        self._force_shutdown = asyncio.Event()
        self._bind_on_start = bind_on_start

    async def start(self) -> None:
        """Bind and start listeners, then mark the health service ready.

        Raises:
            django.core.exceptions.ImproperlyConfigured: If a listener cannot be bound.
        """
        try:
            if self._health_server is not None:
                if self._bind_on_start and self.health_address is not None:
                    self.health_port = _bind(self._health_server, self.health_address)
                    self.health_address = _bound_address(self.health_address, self.health_port)
                await self._health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
                await self._health_servicer.set("readiness", health_pb2.HealthCheckResponse.NOT_SERVING)
                await self._health_servicer.set("liveness", health_pb2.HealthCheckResponse.SERVING)
                await self._health_servicer.set(
                    "centrifugal.centrifugo.proxy.CentrifugoProxy", health_pb2.HealthCheckResponse.NOT_SERVING
                )
                await self._health_server.start()
            if self._bind_on_start:
                self.bound_port = _bind(self._server, self.address)
                self.address = _bound_address(self.address, self.bound_port)
            await self._server.start()
            if self._health_server is not None:
                await self._health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
                await self._health_servicer.set("readiness", health_pb2.HealthCheckResponse.SERVING)
                await self._health_servicer.set(
                    "centrifugal.centrifugo.proxy.CentrifugoProxy", health_pb2.HealthCheckResponse.SERVING
                )
        except BaseException:
            try:
                await self.stop(None, stream_cleanup_timeout=0)
            except Exception:
                logger.exception("Cannot clean up after Centrifugo gRPC startup failure")
            raise

    async def stop(self, grace: float | None, *, stream_cleanup_timeout: float = 5) -> None:
        """Stop calls, then wait for stream-end hooks within a separate timeout.

        Args:
            grace: Seconds to allow in-flight gRPC calls before cancellation;
                ``None`` cancels them immediately.
            stream_cleanup_timeout: Maximum additional seconds to wait for stream hooks.

        Raises:
            ValueError: If the timeout is negative or not finite.
        """
        if not math.isfinite(stream_cleanup_timeout) or stream_cleanup_timeout < 0:
            msg = "stream_cleanup_timeout must be a finite nonnegative number"
            raise ValueError(msg)
        try:
            await self._mark_not_serving()
            await self._server.stop(grace)
            await self._wait_streams(stream_cleanup_timeout)
        finally:
            original_error = sys.exception()
            try:
                await self._stop_health()
            except Exception:
                if original_error is None:
                    raise
                logger.exception("Cannot stop Centrifugo gRPC health listener")

    async def _mark_not_serving(self) -> None:
        if self._health_server is None:
            return
        try:
            for name in ("", "readiness", "centrifugal.centrifugo.proxy.CentrifugoProxy"):
                await self._health_servicer.set(name, health_pb2.HealthCheckResponse.NOT_SERVING)
        except Exception:
            logger.exception("Cannot mark Centrifugo gRPC health as not serving")

    async def _stop_health(self) -> None:
        if self._health_server is None:
            return
        try:
            await self._health_servicer.enter_graceful_shutdown()
        except Exception:
            logger.exception("Cannot shut down Centrifugo gRPC health service")
        finally:
            await self._health_server.stop(None)

    async def _wait_streams(self, wait_seconds: float) -> None:
        streams = self._service.streams.copy()
        if not streams:
            return
        if self._force_shutdown.is_set():
            logger.warning("Forced shutdown with %d stream cleanup hooks pending", len(streams))
            return
        force = asyncio.create_task(self._force_shutdown.wait())
        try:
            deadline = asyncio.get_running_loop().time() + wait_seconds
            while streams and not force.done():
                remaining = max(0, deadline - asyncio.get_running_loop().time())
                done, _ = await asyncio.wait((*streams, force), timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                streams.difference_update(done)
                if not done:
                    break
            if streams:
                logger.warning("Timed out or forced shutdown with %d stream cleanup hooks pending", len(streams))
        finally:
            force.cancel()
            await asyncio.gather(force, return_exceptions=True)

    async def force_stop(self) -> None:
        """Cancel active gRPC calls and skip the remaining stream cleanup wait."""
        self._force_shutdown.set()
        await self._server.stop(None)

    async def wait_for_termination(self) -> None:
        """Wait until the underlying gRPC server stops."""
        await self._server.wait_for_termination()


def _bound_address(address: str, port: int) -> str:
    if not address.startswith("unix:") and address.endswith(":0"):
        return f"{address.rsplit(':', 1)[0]}:{port}"
    return address


def _bind(server: grpc.aio.Server, address: str) -> int:
    try:
        port: int = server.add_insecure_port(address)
    except RuntimeError as exc:
        msg = f"Cannot bind gRPC server to {address!r}"
        raise ImproperlyConfigured(msg) from exc
    if not port:
        msg = f"Cannot bind gRPC server to {address!r}"
        raise ImproperlyConfigured(msg)
    return port


def create_server(
    address: str = "127.0.0.1:10000",
    *,
    maximum_concurrent_rpcs: int | None = None,
    health_address: str | None = None,
) -> GrpcProxyServer:
    """Create a gRPC proxy server using the configured consumer classes.

    The server is not started or bound. It requires a nonempty ``proxy_key`` and accepts
    it only through the ``x-centrifugo-proxy-key`` gRPC metadata field.
    Consumer class paths from ``CENTRIFUGO_SETTINGS['consumers']`` are loaded and
    validated before creating the server. The server retains that registry
    snapshot even if Django settings subsequently change.

    Args:
        address: gRPC listen address, including its port.
        maximum_concurrent_rpcs: Optional limit on simultaneous RPCs, including
            active subscription streams. Excess calls receive RESOURCE_EXHAUSTED.
        health_address: Optional separate, unauthenticated health listener address.
            Restrict access at the network level.

    Returns:
        An unstarted server with the Centrifugo proxy service registered.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If credentials or consumer configuration is invalid.
        ValueError: If the concurrency limit is not a positive integer.
    """
    if not resolve_setting(Settings.proxy_key):
        msg = "CENTRIFUGO_SETTINGS['proxy_key'] must be set for the gRPC server"
        raise ImproperlyConfigured(msg)

    resolve_setting(Settings.client)

    if maximum_concurrent_rpcs is not None and (
        type(maximum_concurrent_rpcs) is not int or maximum_concurrent_rpcs < 1
    ):
        msg = "maximum_concurrent_rpcs must be a positive integer or None"
        raise ValueError(msg)

    registry = _get_registry()
    server = grpc.aio.server(options=(("grpc.so_reuseport", 0),), maximum_concurrent_rpcs=maximum_concurrent_rpcs)
    service = _ProxyService(registry)
    proxy_pb2_grpc.add_CentrifugoProxyServicer_to_server(service, server)  # type: ignore[no-untyped-call]

    health_server = None
    health_servicer = None
    if health_address is not None:
        health_server = grpc.aio.server(options=(("grpc.so_reuseport", 0),))
        health_servicer = cast("Any", health).aio.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, health_server)

    return GrpcProxyServer(
        server,
        service,
        address=address,
        health_server=health_server,
        health_servicer=health_servicer,
        health_address=health_address,
        bind_on_start=True,
    )
