from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from django.core.exceptions import ImproperlyConfigured, PermissionDenied

from django_centrifugo.actions.base import BaseAction
from django_centrifugo.clients import create_async_client
from django_centrifugo.utils.type_inspection import MethodSignature


if TYPE_CHECKING:
    from collections.abc import Sequence

    from cent import AsyncClient

    from django_centrifugo.contracts import SubscribeContext
    from django_centrifugo.errors import ErrorContext, ProxyError
    from django_centrifugo.serialization.base import SerializationBackend


BackendT = TypeVar("BackendT", bound="SerializationBackend")
logger = logging.getLogger(__name__)


async def _close_consumer_client(consumer: Any) -> None:
    if consumer is None:
        return
    close = getattr(consumer, "_close_centrifugo_client", None)
    if close is not None:
        try:
            await close()
        except Exception:
            logger.exception("Centrifugo consumer client cleanup failed")


class Consumer(Generic[BackendT]):
    """Group RPC methods using a shared serialization backend.

    Enable concrete subclasses through dotted class paths in
    ``CENTRIFUGO_SETTINGS['consumers']``. Methods and channel declarations are
    discovered together and validated when the configured registry is loaded,
    before server startup. Inheritance and overrides apply to both action kinds.
    Importing or defining a subclass does not register it. A new consumer is
    constructed for each RPC request or subscription, not shared between them.
    """

    _centrifugo_client: AsyncClient | None = None
    _stream_data: Any

    namespace: ClassVar[str] = ""
    """Optional inherited prefix prepended to RPC names with a dot."""

    channel: ClassVar[str] = ""
    """Optional channel route using Django path converters, such as ``chat:room.<int:room_id>``."""

    channels: ClassVar[Sequence[str]] = ()
    """Additional channel routes handled by this consumer's subscription hooks."""

    @property
    def centrifugo(self) -> AsyncClient:
        """The consumer's lazily created native pycent asynchronous client.

        Configure ``CENTRIFUGO_SETTINGS['client']`` before accessing this property.
        The framework closes the client after the RPC or subscription ends.

        Raises:
            django.core.exceptions.ImproperlyConfigured: If client configuration is missing or invalid.
            RuntimeError: If the consumer's client lifetime has ended.
        """
        if getattr(self, "_centrifugo_client_closed", False):
            msg = "The consumer's Centrifugo client is already closed"
            raise RuntimeError(msg)

        client = getattr(self, "_centrifugo_client", None)
        if client is None:
            client = create_async_client()
            self._centrifugo_client = client

        return client

    async def _close_centrifugo_client(self) -> None:
        self._centrifugo_client_closed = True

        client = getattr(self, "_centrifugo_client", None)
        if client is not None:
            self._centrifugo_client = None
            await client.aclose()

    async def on_subscribe(self, data: Any, context: SubscribeContext) -> dict[str, Any] | None:  # noqa: ARG002
        """Authorize a stream subscription and optionally return initial JSON data.

        Override this method when declaring a channel. The default denies access.
        The ``data`` annotation determines validation using the consumer's
        serialization backend. Missing subscription data is passed as ``None``;
        use an optional model or annotate ``data`` as ``None`` when appropriate.
        Validation failures invoke :meth:`on_error` before this method runs.

        Args:
            data: Validated subscription payload, annotated with a model supported
                by this consumer's serialization backend, or ``None`` if no data is expected.
            context: Connection identity, channel parameters, and metadata.

        Returns:
            Optional JSON object sent in the subscription reply.

        Raises:
            django.core.exceptions.PermissionDenied: If subscription is forbidden.
        """
        raise PermissionDenied

    async def on_stream_end(self, context: SubscribeContext) -> None:
        """Clean up after an accepted subscription stream ends.

        The reason is not known and the hook may not run after process failure.

        Args:
            context: The same context passed to ``on_subscribe``.
        """

    async def on_error(self, error: ErrorContext) -> ProxyError | None:  # noqa: ARG002
        """Handle an error raised while processing this consumer's request.

        Called for RPC validation and execution, subscription setup, and stream
        cleanup. Failures before a consumer is selected use the configured
        global error handler; authentication failures are rejected by gRPC.
        Do not expose exception details to clients. Exceptions raised here
        produce a safe internal error.

        Args:
            error: Classified failure and the associated request context, if available.

        Returns:
            A client-safe error, or ``None`` to use the global error handler.
            For stream cleanup, the response is discarded because the stream
            has already ended.
        """
        return None

    @classmethod
    def _configure_subscription(cls, backend_class: type[SerializationBackend]) -> Any:
        method = cls.on_subscribe
        if method is Consumer.on_subscribe:
            return Any

        if not inspect.iscoroutinefunction(method):
            msg = f"{cls.__qualname__}.on_subscribe must be an async method"
            raise ImproperlyConfigured(msg)

        try:
            signature = MethodSignature.from_method(method, target_class=cls, annotation_names={"data"})
            annotation = signature.annotations["data"]
            signature.signature.bind(None, data=None, context=None)
        except (KeyError, TypeError, NameError) as exc:
            msg = f"{cls.__qualname__}.on_subscribe must accept annotated data and context: {exc}"
            raise ImproperlyConfigured(msg) from exc

        try:
            backend = backend_class()
        except Exception as exc:
            msg = f"Cannot instantiate backend for {cls.__qualname__}"
            raise ImproperlyConfigured(msg) from exc

        if annotation is not type(None) and not backend.is_supported_annotation(annotation):
            msg = f"Backend {backend_class.__qualname__} does not support {annotation!r}"
            raise ImproperlyConfigured(msg)

        return annotation

    @classmethod
    def _discover_actions(cls) -> dict[str, BaseAction]:
        """Collect all action declarations by method name, respecting method resolution order."""
        methods: dict[str, Any] = {}
        for base in reversed(cls.__mro__):
            methods.update(vars(base))
        return {name: method for name, method in methods.items() if isinstance(method, BaseAction)}
