from __future__ import annotations

import asyncio
import logging
import math
import os
import signal
import sys
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Annotated, Any, cast, override

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import CommandError
from django.utils import autoreload
from django_typer.management import TyperCommand
from rich.console import Console
from rich.text import Text
from typer import Option

from django_centrifugo.grpc._access_log import access_logger
from django_centrifugo.grpc.runner import GrpcServerRunner
from django_centrifugo.grpc.server import create_server
from django_centrifugo.management.commands._startup_info import _startup_info, _StartupInfo
from django_centrifugo.settings.keys import Settings
from django_centrifugo.settings.resolver import resolve_setting


if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path
    from types import FrameType
    from typing import IO

logger = logging.getLogger(__name__)


def _has_access_handler() -> bool:
    current: logging.Logger | None = access_logger
    while current is not None:
        if any(not isinstance(handler, logging.NullHandler) for handler in current.handlers):
            return True
        if not current.propagate:
            return False
        current = current.parent
    return False


@contextmanager
def _access_logging(stream: Any, *, enabled: bool) -> Generator[None, None, None]:
    old_disabled = access_logger.disabled
    old_level = access_logger.level
    handler: logging.Handler | None = None
    try:
        if not enabled:
            access_logger.disabled = True
        elif not access_logger.disabled and access_logger.propagate and not _has_access_handler():
            handler = logging.StreamHandler(stream)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
            access_logger.addHandler(handler)
            if access_logger.level == logging.NOTSET:
                access_logger.setLevel(logging.INFO)
        yield
    finally:
        if handler is not None:
            access_logger.removeHandler(handler)
            handler.close()
        access_logger.setLevel(old_level)
        access_logger.disabled = old_disabled


class _SignalDispatcher:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.runner: GrpcServerRunner | None = None
        self.pending = 0
        self.received_signal = False

    def handle(self, signum: int, _frame: FrameType | None) -> None:
        self.received_signal = True
        self.loop.call_soon_threadsafe(self._deliver, signum)

    def _deliver(self, signum: int) -> None:
        logger.info("Received signal %s; requesting gRPC shutdown", signum)
        if self.runner is None:
            self.pending += 1
        else:
            self.runner.request_shutdown()

    def bind(self, runner: GrpcServerRunner) -> None:
        self.runner = runner
        for _ in range(self.pending):
            runner.request_shutdown()
        self.pending = 0


@contextmanager
def _capture_signals(loop: asyncio.AbstractEventLoop) -> Generator[_SignalDispatcher, None, None]:
    dispatcher = _SignalDispatcher(loop)
    previous: dict[signal.Signals, Any] = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[sig] = signal.signal(sig, dispatcher.handle)
            except (ValueError, OSError):
                logger.warning("Cannot install signal handler for %s", sig.name)
        yield dispatcher
    finally:
        for previous_signal, handler in previous.items():
            signal.signal(previous_signal, handler)


class _ReloadWatcher:
    def __init__(
        self, loop: asyncio.AbstractEventLoop, runner: GrpcServerRunner, on_change: Callable[[Path], None]
    ) -> None:
        self.reloader = autoreload.StatReloader()
        self.loop = loop
        self.runner = runner
        self.on_change = on_change
        self.changed = False
        self.started = False
        self.thread = threading.Thread(target=self.reloader.run_loop, name="centrifugo-autoreload", daemon=True)

    def _changed(self, sender: Any, *, file_path: Path, **_kwargs: Any) -> bool:
        if sender is not self.reloader:
            return False
        self.changed = True
        self.reloader.stop()
        self.loop.call_soon_threadsafe(self.on_change, file_path)
        self.loop.call_soon_threadsafe(self.runner.request_shutdown)
        return True

    def start(self) -> None:
        autoreload.file_changed.connect(self._changed, weak=False)
        try:
            self.thread.start()
            self.started = True
        except Exception:
            autoreload.file_changed.disconnect(self._changed)
            raise

    async def stop(self) -> None:
        self.reloader.stop()
        await asyncio.to_thread(self.thread.join, 2)
        autoreload.file_changed.disconnect(self._changed)


class Command(TyperCommand):
    """Run the Centrifugo gRPC proxy server in a separate process."""

    help = "Run the Centrifugo gRPC proxy server."  # type: ignore[mutable-override]

    def _reload_notice(self, file_path: Path) -> None:
        self.stdout.write(f"File changed: {file_path}; restarting Centrifugo gRPC server")
        self.stdout.flush()

    @override
    def handle(  # noqa: C901
        self,
        *,
        address: Annotated[str, Option(help="gRPC listen address")] = "127.0.0.1:10000",
        maximum_concurrent_rpcs: Annotated[
            int | None,
            Option(help="Maximum active RPCs, including subscription streams"),
        ] = None,
        health_address: Annotated[
            str | None,
            Option(help="Separate unauthenticated gRPC health listen address"),
        ] = None,
        shutdown_grace: Annotated[float, Option(help="Seconds to allow in-flight RPCs")] = 5.0,
        stream_cleanup_timeout: Annotated[float, Option(help="Additional seconds to await stream-end hooks")] = 5.0,
        reload: Annotated[bool, Option("--reload", help="Restart on Python changes (development only)")] = False,
        no_access_log: Annotated[bool, Option("--no-access-log", help="Disable gRPC access logs")] = False,
    ) -> None:
        if maximum_concurrent_rpcs is not None and maximum_concurrent_rpcs <= 0:
            msg = "maximum-concurrent-rpcs must be a positive integer"
            raise CommandError(msg)

        if any(not math.isfinite(value) or value < 0 for value in (shutdown_grace, stream_cleanup_timeout)):
            msg = "timeouts must be a finite nonnegative number"
            raise CommandError(msg)

        if reload and "runcentrifugogrpc" not in sys.argv:
            msg = "--reload is only supported when launching the management command as a process"
            raise CommandError(msg)

        async def serve() -> bool:
            loop = asyncio.get_running_loop()
            with _capture_signals(loop) as dispatcher:
                try:
                    info = await _startup_info()

                    if dispatcher.received_signal:
                        return False

                    server = create_server(
                        address,
                        maximum_concurrent_rpcs=maximum_concurrent_rpcs,
                        health_address=health_address,
                    )
                except ImproperlyConfigured as exc:
                    raise CommandError(str(exc)) from exc

                runner = GrpcServerRunner(
                    server,
                    shutdown_grace=shutdown_grace,
                    stream_cleanup_timeout=stream_cleanup_timeout,
                )
                dispatcher.bind(runner)
                watcher = _ReloadWatcher(loop, runner, self._reload_notice) if reload else None

                def ready() -> None:
                    if watcher is not None:
                        watcher.start()

                    client_config = resolve_setting(Settings.client) if info is not None else None
                    startup = _StartupInfo(
                        address=server.address,
                        pid=os.getpid(),
                        maximum_concurrent_rpcs=maximum_concurrent_rpcs,
                        reload=reload,
                        shutdown_grace=shutdown_grace,
                        stream_cleanup_timeout=stream_cleanup_timeout,
                        health_address=server.health_address,
                        centrifugo_url=client_config.get("api_endpoint") if client_config is not None else None,
                        centrifugo_info=info,
                    )

                    console = Console(
                        file=cast("IO[str]", self.stdout),
                        force_terminal=True if self.force_color else None,
                        color_system="standard" if self.force_color else "auto",
                        no_color=self.no_color,
                        markup=False,
                        highlight=False,
                    )

                    settings_table, nodes_table = startup.tables()
                    console.print(settings_table)

                    if nodes_table is not None:
                        console.print(nodes_table)

                    console.print(Text("Ready.", style="green"))
                    self.stdout.flush()

                try:
                    try:
                        await runner.run(on_ready=ready)
                    except ImproperlyConfigured as exc:
                        raise CommandError(str(exc)) from exc
                finally:
                    if watcher is not None and watcher.started:
                        await watcher.stop()
                return bool(watcher and watcher.changed and not dispatcher.received_signal)

        with _access_logging(self.stdout, enabled=not no_access_log):
            reload_requested = asyncio.run(serve())

        if reload_requested:
            os.execv(sys.executable, autoreload.get_child_arguments())  # noqa: S606
