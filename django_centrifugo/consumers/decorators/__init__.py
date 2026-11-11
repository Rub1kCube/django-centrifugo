"""Decorators for consumer RPC methods and subscription streams."""

from django_centrifugo.consumers.decorators.rpc import rpc
from django_centrifugo.consumers.decorators.stream import stream


__all__ = ["rpc", "stream"]
