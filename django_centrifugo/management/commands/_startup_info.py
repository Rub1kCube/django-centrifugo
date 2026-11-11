from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import cent
from django.core.management.base import CommandError
from rich.table import Table

from django_centrifugo.clients import create_async_client
from django_centrifugo.settings.keys import Settings
from django_centrifugo.settings.resolver import resolve_setting


if TYPE_CHECKING:
    from cent import InfoResult, NodeResult


async def _startup_info() -> InfoResult | None:
    config = resolve_setting(Settings.client)
    if config is None:
        return None
    try:
        async with create_async_client() as client:
            return await client.info()
    except cent.CentError as exc:
        msg = f"Centrifugo startup check failed: {exc}"
        raise CommandError(msg) from exc


@dataclass(frozen=True, slots=True)
class _NodeInfo:
    name: str
    version: str
    clients: str
    users: str
    channels: str
    uptime: str

    @staticmethod
    def _node_value(value: str | int) -> str:
        if isinstance(value, str) and value:
            return "".join(char if char.isprintable() else "?" for char in value)

        if type(value) is int and value >= 0:
            return str(value)
        return "-"

    @classmethod
    def from_node(cls, node: NodeResult) -> _NodeInfo:
        return cls(
            name=cls._node_value(node.name),
            version=cls._node_value(node.version),
            clients=cls._node_value(node.num_clients),
            users=cls._node_value(node.num_users),
            channels=cls._node_value(node.num_channels),
            uptime=cls._node_value(node.uptime),
        )


@dataclass(frozen=True, slots=True)
class _StartupInfo:
    address: str
    pid: int
    maximum_concurrent_rpcs: int | None
    reload: bool
    shutdown_grace: float
    stream_cleanup_timeout: float
    health_address: str | None
    centrifugo_url: str | None
    centrifugo_info: InfoResult | None

    def tables(self) -> tuple[Table, Table | None]:
        settings = Table(title="Centrifugo gRPC Proxy", show_header=False, border_style="cyan")
        settings.add_column("Setting", style="bold")
        settings.add_column("Value")
        settings.add_row("gRPC:", self.address)
        settings.add_row("PID:", str(self.pid))
        settings.add_row("Concurrency:", str(self.maximum_concurrent_rpcs or "unlimited"))
        settings.add_row("Reload:", str(self.reload))
        settings.add_row("Shutdown:", f"grace {self.shutdown_grace}s, stream cleanup {self.stream_cleanup_timeout}s")

        if self.health_address is not None:
            settings.add_row("Health:", self.health_address)

        if self.centrifugo_info is None:
            settings.add_row("Centrifugo:", "check skipped (client not configured)")
            return settings, None

        settings.add_row("Centrifugo:", f"{self.centrifugo_url}")
        nodes = Table(title=f"Nodes: {len(self.centrifugo_info.nodes)}", border_style="cyan")

        for column in ("Node", "Version", "Clients", "Users", "Channels", "Uptime"):
            nodes.add_column(column)

        for item in self.centrifugo_info.nodes:
            node = _NodeInfo.from_node(item)
            uptime = f"{node.uptime}s" if node.uptime != "-" else "-"
            nodes.add_row(node.name, node.version, node.clients, node.users, node.channels, uptime)

        return settings, nodes
