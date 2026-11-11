"""Group RPC methods into consumers."""

from django_centrifugo.consumers.consumer import Consumer
from django_centrifugo.consumers.decorators import rpc, stream
from django_centrifugo.consumers.registry import resolve_stream


__all__ = ["Consumer", "resolve_stream", "rpc", "stream"]
