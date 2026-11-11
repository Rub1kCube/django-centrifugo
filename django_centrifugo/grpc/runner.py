from __future__ import annotations

import asyncio
import logging
import math
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable

    from django_centrifugo.grpc.server import GrpcProxyServer


logger = logging.getLogger(__name__)


class GrpcServerRunner:
    """Run a proxy server until it terminates or shutdown is requested.

    Signal handling belongs to the caller, so the runner is usable in an
    existing event loop. The first shutdown request is graceful; a second
    requests immediate cancellation of calls and skips the stream cleanup wait.

    Args:
        server: The unstarted proxy server.
        shutdown_grace: Seconds for in-flight gRPC calls to finish.
        stream_cleanup_timeout: Additional seconds to wait for stream hooks.

    Raises:
        ValueError: If a timeout is negative or non-finite.
    """

    def __init__(
        self,
        server: GrpcProxyServer,
        *,
        shutdown_grace: float = 5,
        stream_cleanup_timeout: float = 5,
    ) -> None:
        for name, value in (("shutdown_grace", shutdown_grace), ("stream_cleanup_timeout", stream_cleanup_timeout)):
            if not math.isfinite(value) or value < 0:
                msg = f"{name} must be a finite nonnegative number"
                raise ValueError(msg)
        self.server = server
        """The proxy server owned by this runner."""
        self.shutdown_grace = shutdown_grace
        """Seconds allowed for in-flight calls."""
        self.stream_cleanup_timeout = stream_cleanup_timeout
        """Additional seconds allowed for subscription cleanup hooks."""
        self._shutdown = asyncio.Event()
        self._force = asyncio.Event()

    def request_shutdown(self) -> None:
        """Request graceful shutdown, or force it on a subsequent request.

        Call this method from the runner's event-loop thread.
        """
        if self._shutdown.is_set():
            self._force.set()
        else:
            self._shutdown.set()

    async def _stop(self) -> None:
        logger.info(
            "Stopping Centrifugo gRPC server (grace=%s, stream cleanup timeout=%s)",
            self.shutdown_grace,
            self.stream_cleanup_timeout,
        )
        stop_task = asyncio.create_task(
            self.server.stop(self.shutdown_grace, stream_cleanup_timeout=self.stream_cleanup_timeout)
        )
        force_task = asyncio.create_task(self._force.wait())
        try:
            done, _ = await asyncio.wait((stop_task, force_task), return_when=asyncio.FIRST_COMPLETED)
            if force_task in done and not stop_task.done():
                logger.warning("Forcing Centrifugo gRPC server shutdown")
                try:
                    await self.server.force_stop()
                except Exception:
                    logger.exception("Cannot force Centrifugo gRPC server shutdown")
            await stop_task
            logger.info("Centrifugo gRPC server stopped")
        finally:
            force_task.cancel()
            await asyncio.gather(force_task, return_exceptions=True)

    async def run(self, *, on_ready: Callable[[], None] | None = None) -> None:
        """Start, wait, and always stop the server, including on startup failure.

        Args:
            on_ready: Callback called after successful startup unless shutdown
                was already requested. Exceptions trigger server cleanup.
        """
        shutdown_task: asyncio.Task[bool] | None = None
        server_task: asyncio.Task[None] | None = None
        try:
            if self._shutdown.is_set():
                return
            await self.server.start()
            if self._shutdown.is_set():
                return
            if on_ready is not None:
                on_ready()
            shutdown_task = asyncio.create_task(self._shutdown.wait())
            server_task = asyncio.create_task(self.server.wait_for_termination())
            await asyncio.wait((shutdown_task, server_task), return_when=asyncio.FIRST_COMPLETED)
            if server_task.done():
                server_task.result()
        finally:
            original_error = sys.exception()
            try:
                await self._stop()
            except Exception:
                if original_error is None:
                    raise
                logger.exception("Centrifugo gRPC server shutdown failed")
            finally:
                await _cancel_waiters(shutdown_task, server_task)


async def _cancel_waiters(shutdown_task: asyncio.Task[bool] | None, server_task: asyncio.Task[None] | None) -> None:
    for task in (shutdown_task, server_task):
        if task is not None and not task.done():
            task.cancel()
    if shutdown_task is not None:
        await asyncio.gather(shutdown_task, return_exceptions=True)
    if server_task is not None:
        await asyncio.gather(server_task, return_exceptions=True)
