from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from typing_extensions import TypeForm


if TYPE_CHECKING:
    from django_centrifugo.consumers.consumer import Consumer
    from django_centrifugo.serialization.base import SerializationBackend


@dataclass(frozen=True, slots=True)
class DocumentationMetadata:
    """Action documentation, including the already applied docstring fallbacks."""

    summary: str | None
    description: str | None
    tags: frozenset[str]
    deprecated: bool


@dataclass(frozen=True, slots=True)
class RpcMetadata:
    """A registered RPC with its effective backend and wire payload annotations.

    ``output_annotation`` is the validated output model, including ``Annotated``
    metadata, or ``NoneType`` for an RPC returning JSON null. It does not include
    the Python dictionary alternative allowed by ``Output[T]``.
    """

    name: str
    method_name: str
    backend_class: type[SerializationBackend]
    data_annotation: TypeForm[Any]
    output_annotation: TypeForm[Any]
    documentation: DocumentationMetadata


@dataclass(frozen=True, slots=True)
class StreamMetadata:
    """The typed publications produced by a channel's configured stream."""

    method_name: str
    output_annotation: TypeForm[Any]
    close_on_complete: bool
    documentation: DocumentationMetadata


@dataclass(frozen=True, slots=True)
class ChannelParameterMetadata:
    """A Django route parameter with its converter name and matching pattern."""

    name: str
    converter: str
    pattern: str


@dataclass(frozen=True, slots=True)
class ChannelMetadata:
    """A subscription route and its optional typed publications.

    ``route`` preserves the Django route; ``address`` uses ``{parameter}``
    placeholders. ``data_annotation`` comes from subscription validation, not
    the stream method. No schema is inferred for initial subscription replies
    or for publications on a route without a stream.
    """

    route: str
    address: str
    parameters: tuple[ChannelParameterMetadata, ...]
    backend_class: type[SerializationBackend]
    data_annotation: TypeForm[Any]
    stream: StreamMetadata | None


@dataclass(frozen=True, slots=True)
class ConsumerMetadata:
    """Contracts owned by one concrete registered consumer, including inherited actions."""

    consumer_class: type[Consumer[Any]]
    rpc_actions: tuple[RpcMetadata, ...]
    channels: tuple[ChannelMetadata, ...]


@dataclass(frozen=True, slots=True)
class ApplicationMetadata:
    """A snapshot of selected consumers in runtime registration order."""

    consumers: tuple[ConsumerMetadata, ...]
