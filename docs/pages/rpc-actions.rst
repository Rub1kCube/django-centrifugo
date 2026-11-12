RPC actions
===========

The Django integration receives Centrifugo v6 gRPC proxy RPC requests and
subscription streams. Other Centrifugo proxy methods, including connect, are
not implemented. It accepts JSON RPC object payloads; binary encoding is not
supported. Install the optional Pydantic integration with
``pip install django-centrifugo[pydantic]`` if using Pydantic models.

Configure a shared secret and dotted paths to enabled consumer classes in Django settings:

.. code-block:: python

   CENTRIFUGO_SETTINGS = {
       "proxy_key": "load-a-long-random-secret-from-your-secret-store",
       "consumers": ["myapp.actions.ChatConsumer"],
   }

Start the dedicated gRPC server as a separate process:

.. code-block:: console

   python manage.py runcentrifugogrpc --address 127.0.0.1:10000

When ``CENTRIFUGO_SETTINGS['client']`` is configured, the command first calls the
authenticated Centrifugo HTTP API ``info`` method. After the listener starts,
the startup tables show the API address, node names and versions, client,
user and channel counts, and uptime. A dash indicates unavailable data. These
values are a snapshot taken during startup.
Use ``--no-color`` to disable colors or ``--force-color`` to enable them when
output is redirected. Run the command with ``--help`` to see its options.
This request also checks connectivity and API credentials; it uses pycent's
configured ``request_timeout``. Start Centrifugo before this command. If the
request fails, the command exits without starting the gRPC listener.
Without client configuration, the check is skipped. This startup check applies to
the management command; applications using the server or runner directly manage
their own dependency checks. The server does not continuously monitor Centrifugo.

The server installs shutdown handlers before announcing readiness. A first
SIGINT or SIGTERM starts graceful shutdown; a second requests immediate gRPC
cancellation and skips the remaining wait for stream cleanup. Previous signal
handlers are restored when the command exits. The printed address includes the
actual port when binding to port ``0``.

Shutdown has two sequential time budgets: ``--shutdown-grace`` seconds for
in-flight calls, followed by up to ``--stream-cleanup-timeout`` seconds for
subscription hooks (both default to 5). Long-lived streams normally remain
active until the grace period ends. Stream cleanup is best effort: blocking
threads, tasks that ignore cancellation, or process termination may exceed
these budgets. Set the process manager's termination timeout accordingly.
When a backend stream closes, Centrifugo may cause clients to resubscribe;
write ``on_subscribe`` and ``on_stream_end`` to tolerate overlapping streams
and idempotently manage resources belonging to each stream.

Add ``--health-address 127.0.0.1:10001`` to expose the standard gRPC Health
service on a separate listener. It reports ``SERVING`` after proxy startup and
``NOT_SERVING`` during shutdown for both the empty service name and
``centrifugal.centrifugo.proxy.CentrifugoProxy``. The health listener is
unauthenticated and unencrypted; restrict network access to it. It is disabled
by default. It does not test the database or other external dependencies, and
its calls do not consume the proxy's concurrency limit. Kubernetes gRPC probes
must be able to reach the configured listener.
The service name ``readiness`` follows the same readiness state; ``liveness``
remains ``SERVING`` during the graceful drain until the health listener stops.
Port reuse is disabled for both listeners so a second server cannot silently
share their address; run multiple instances on separate addresses.

For local development, ``--reload`` watches imported Python files and restarts
the process after a change. The startup banner shows ``Reload: True``, and the
command prints the changed file before stopping the server. Restarting closes
subscription streams. This option
is intended for a command-line process, not production or ``call_command``.
Django's ordinary system checks run on each launch; ``--skip-checks`` disables
them.

Access logs
-----------

The management command logs RPCs and subscription events through the standard
Python logger ``django_centrifugo.grpc.access``. If no logging handler is
configured for it or its ancestors, the command installs a temporary console
handler at INFO level. Use ``--no-access-log`` to disable these records for the
command. Configured handlers and levels are respected instead of adding another
handler. Applications using the server or runner directly can configure the
same logger through Django's ``LOGGING`` setting.

.. code-block:: text

   2026-11-05 12:00:00 INFO    RPC greeting.hello OK grpc=OK 3.2ms
   2026-11-05 12:00:01 INFO    RPC greeting.hello ERROR grpc=OK code=400 1.5ms
   2026-11-05 12:00:02 INFO    SUBSCRIBE chat:room.5 ACCEPTED grpc=- 2.1ms
   2026-11-05 12:01:02 INFO    SUBSCRIBE chat:room.5 CLOSED grpc=- 60002.3ms

RPC records are emitted when the handler returns or is cancelled. Application
errors carry a Centrifugo error code even when the handler returns a gRPC OK
response. Subscription acceptance or rejection is logged when the handler
produces its first response; closure is logged after stream cleanup. The elapsed
time for closure includes cleanup. A dash means the final transport status is
not known at that point. A cancelled handler does not necessarily tell us the
status seen by the remote client. These records describe handler events, not
confirmation of network delivery.

Authentication failures are logged at WARNING without including the request
target; other access events use INFO. Request bodies, metadata, keys, and
separate client and user identifiers are not logged. Method names and channel
names are included after removing control characters and limiting them to 128
characters; they may themselves contain application identifiers. Log records
also expose ``operation``, ``target``, ``outcome``, ``grpc_status``,
``error_code`` and ``duration_ms`` for custom formatters. Health requests and
calls rejected by gRPC before a proxy handler runs, including calls exceeding
the concurrency limit, are outside this log.

For an application that already owns an event loop,
:class:`~django_centrifugo.grpc.runner.GrpcServerRunner` provides an async
``run()`` method and a ``request_shutdown()`` method. The caller owns signal
handling, and a second request forces shutdown. A server returned by
:func:`~django_centrifugo.grpc.server.create_server` binds its listeners during
``start()``, and its ``address`` and ``health_address`` include the assigned
ports only after startup. Binding errors are raised from ``start()``.

Optionally set ``--maximum-concurrent-rpcs`` to a positive integer to bound
active calls. Active subscription streams count towards this limit for their
entire lifetime; calls above the limit receive gRPC ``RESOURCE_EXHAUSTED``.
Size the limit for both streams and RPC traffic. The default is unlimited.
The same option is available through
:func:`~django_centrifugo.grpc.server.create_server`.

The server checks Django database connections before and after each RPC and
each subscription hook, including its error handler. In particular, connections
are checked after ``on_subscribe`` rather than being held until the stream ends.
This uses Django's ``close_old_connections``: it closes expired or unusable
connections, not necessarily every connection. For async applications Django
recommends disabling persistent connections with ``CONN_MAX_AGE = 0`` and
using a database connection pool when needed. Cleanup failures are logged and
do not replace a handler's exception or cancellation. Connections opened in
independent threads or tasks created by application code need their own
lifecycle management. For transactions, run the entire synchronous operation
using a thread-sensitive adapter such as ``sync_to_async``.

Use an address reachable from Centrifugo. The built-in server uses an
unencrypted gRPC listener; isolate it on a trusted network or provide TLS using
an appropriately configured proxy. Configure Centrifugo v6 to send the secret
as static gRPC metadata for **both** proxy types. Replace the secret and backend
address in this fragment:

.. code-block:: json

   {
     "rpc": {
       "proxy": {
         "endpoint": "grpc://django:10000",
         "grpc": {"static_metadata": {"x-centrifugo-proxy-key": "load-from-secret-store"}}
       },
       "namespaces": [{"name": "chat", "proxy_enabled": true}]
     },
     "channel": {
       "proxy": {
         "subscribe_stream": {
           "endpoint": "grpc://django:10000",
           "grpc": {"static_metadata": {"x-centrifugo-proxy-key": "load-from-secret-store"}}
         }
       },
       "namespaces": [{"name": "chat", "subscribe_stream_proxy_enabled": true}]
     }
   }

Use a secret that clients cannot supply or override, configure connection
and channel authentication in Centrifugo, and protect the service-to-service
connection. The gRPC server trusts the user identifier from the authenticated
proxy; missing, duplicate, or invalid key metadata is rejected. Centrifugo
subscription streams are experimental and apply to eligible client-side
subscriptions; subscription tokens and user-limited channels can bypass the
proxy. A stream namespace cannot simultaneously use ordinary subscribe,
publish, or sub-refresh proxies. See the Centrifugo proxy documentation for
the applicable server version.

Actions
-------

A consumer groups related RPC methods. Declare the serialization backend as its
generic parameter and decorate each asynchronous method with
:func:`~django_centrifugo.consumers.decorators.rpc.rpc`. The ``data`` annotation
specifies the payload model; the return annotation describes the response.
A new consumer and backend instance are created for each request, so consumer
instances do not retain connection state between calls. Importing or defining a
consumer does not register its handlers. Only the concrete classes listed in
``CENTRIFUGO_SETTINGS['consumers']`` are enabled; inherited methods and routes
are included, respecting overrides.

RPC and stream declarations share one discovery and registration process. Each
consumer's methods are collected in one pass over its method resolution order,
then both action kinds are configured through
:class:`~django_centrifugo.actions.base.BaseAction`. Overriding a method replaces
its inherited declaration, including when switching between RPC and stream or
replacing it with an ordinary method. RPC names and channel routes use separate
lookup indexes, so the same string may identify an RPC and a channel. Routes
declared through ``channel`` or ``channels`` are combined with stream routes
during the same consumer registry build.

``consumers`` accepts a list or tuple of nonempty dotted class paths and defaults
to an empty tuple. The gRPC server loads and validates all selected classes
before creating its listener. Missing classes, non-consumer targets, abstract or
unbound generic classes, repeated classes (including aliases), duplicate RPC
names, and duplicate channel declarations across consumers raise configuration
errors. A failed build does not publish a partially registered configuration.
The order of classes does not give overlapping routes priority.

Each server keeps a registry snapshot with its configured actions, compiled
channel patterns, and subscription validation settings. Changing Django settings
invalidates the cache for subsequent loads, including ``override_settings`` in
tests; an existing server keeps its previous snapshot. Restart the server to
apply new consumer declarations. Public ``resolve_action`` and ``resolve_stream``
load the current configured registry on first use, so they can also surface
configuration errors before a server is created.

RPC lookup uses a dictionary with average O(1) lookup by method name. Channel
lookup checks the compiled patterns and rejects multiple matches; it remains
linear in the number of registered routes. A successful match includes the
configured stream, avoiding a second route search. String processing and
pattern-matching costs also depend on the channel and converters.

Migrating from module registration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Replace the removed ``action_modules`` setting with ``consumers`` and list each
class explicitly, for example ``"myapp.actions.ChatConsumer"`` rather than
``"myapp.actions"``. Listing a subclass does not separately enable its base
classes. Listing both a base and subclass with the same inherited RPC name or
channel is a conflict. An omitted or empty ``consumers`` list enables no handlers;
importing a consumer from another module does not change that.

Method backends
~~~~~~~~~~~~~~~

An individual method can override the consumer's default backend with the
``backend_serializer`` argument. Pass a backend class, not an instance. The
selected backend validates that method's input and serializes its model results;
other methods keep the consumer's default. An inherited RPC method retains its
override.

``@rpc`` creates an :class:`~django_centrifugo.actions.rpc.RpcAction` descriptor.
Each registry build configures a separate action for each selected consumer,
leaving an inherited declaration unchanged. The registry retains the configured action and its consumer class.
The server calls the action to validate incoming dictionaries,
invoke the method with the resulting model, and serialize the result. Direct
calls through a consumer instance continue to call the original method and
therefore expect an already validated model. A configured action can also be
called with a dictionary, :class:`~django_centrifugo.contracts.RpcContext`, and
an explicit ``consumer`` instance. The caller manages that instance's resources.

Dependency injection
~~~~~~~~~~~~~~~~~~~~

Consumers can use an application-owned dependency injection container, for
example through a mixin or a decorator. No particular container is required.
Apply an injection decorator to the method before ``@rpc`` or ``@stream``:

.. code-block:: python

   class ChatConsumer(Consumer[MyBackend]):
       @rpc("send")
       @inject  # Provided by the application or a DI integration
       async def send(
           self,
           data: SendMessage,
           context: RpcContext,
           service: InjectedSendMessageService,
       ) -> MessageResult:
           return await service.execute(data)

Here the application supplies the backend, models, service and decorator. The
injection decorator must resolve ``service`` and expose a public signature that
accepts ``self``, ``data``, and ``context``, with annotations for ``data`` and
the return value. A wrapper can publish this signature using ``__signature__``.
Ordinary extra parameters with defaults are also accepted; the application is
responsible for ensuring its injection decorator resolves dependency markers.
The same signature rules apply to an overridden ``on_subscribe`` hook, except
that its return annotation is not used for output model validation.

For example, an application using Dishka can provide the decorator and service
annotation above as follows:

.. code-block:: python

   from dishka import FromDishka
   from dishka.integrations.base import wrap_injection

   from myproject.container import container  # An application-owned async container
   from myproject.services import SendMessageService

   InjectedSendMessageService = FromDishka[SendMessageService]

   def inject(method):
       return wrap_injection(
           func=method,
           container_getter=lambda args, kwargs: container,
           is_async=True,
           manage_scope=True,
       )

The application must register the service and manage the container's lifetime,
including closing it at shutdown. A scope opened by a method decorator covers
that method, not input validation, output validation, or ``on_error``. Other DI
systems may require their own adapter to publish the correct signature or manage
their resources.

A decorated stream method must itself remain an async generator function. Its
injection wrapper must keep dependencies open during iteration and release them
when the generator is closed, including on errors or cancellation. An arbitrary
async iterator is not accepted as a substitute for an async generator function.

.. code-block:: python

   import msgspec
   from pydantic import BaseModel
   from django_centrifugo.consumers import Consumer, rpc
   from django_centrifugo.contracts import RpcContext
   from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend
   from django_centrifugo.plugins.pydantic.serializator import PydanticSerializationBackend

   class Message(msgspec.Struct):
       text: str

   class PydanticMessage(BaseModel):
       text: str

   class MixedConsumer(Consumer[MsgspecSerializationBackend]):
       @rpc("chat:msgspec")
       async def msgspec_message(self, data: Message, context: RpcContext) -> Message:
           return data

       @rpc("chat:pydantic", backend_serializer=PydanticSerializationBackend)
       async def pydantic_message(self, data: PydanticMessage, context: RpcContext) -> PydanticMessage:
           return data

.. code-block:: python

   import msgspec
   from django_centrifugo.consumers import Consumer, rpc
   from django_centrifugo.contracts import RpcContext
   from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend

   class Message(msgspec.Struct):
       text: str

   class SentMessage(msgspec.Struct):
       user: str
       text: str

   class ChatConsumer(Consumer[MsgspecSerializationBackend]):
       @rpc("chat:send")
       async def send_message(self, data: Message, context: RpcContext) -> SentMessage:
           return SentMessage(user=context.user, text=data.text)

       @rpc("chat:acknowledge")
       async def acknowledge(self, data: Message, context: RpcContext) -> None:
           # Perform an operation without returning application data.
           pass

RPC documentation metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``summary``, ``description``, ``tags`` and ``deprecated`` on ``@rpc`` to
describe an action for documentation. They do not affect request handling.

.. code-block:: python

   class ChatConsumer(Consumer[MsgspecSerializationBackend]):
       @rpc(
           "chat:send",
           summary="Send a message",
           description="Validate and store a chat message.",
           tags=["chat"],
           deprecated=False,
       )
       async def send_message(self, data: Message, context: RpcContext) -> Message:
           return data

When ``summary`` or ``description`` is omitted or ``None``, the corresponding
value is taken from the method's docstring: the first paragraph supplies the
summary and the full docstring supplies the description. Explicit values
take precedence independently. If no corresponding text is available, the
value is ``None``. Tags default to an empty tuple and are copied when the
decorator is called. An inherited method retains its metadata; an overridden
method uses its own decorator and docstring.

The resolved metadata is available on registered
:class:`~django_centrifugo.actions.rpc.RpcAction` objects. It prepares actions
for future documentation generation; it does not itself generate AsyncAPI.
Each action retains the method selected at registration and invokes it with a
new consumer instance for each request. Replacing the class attribute later
does not replace the registered method.

RPC namespaces
~~~~~~~~~~~~~~

To share a prefix, set :attr:`~django_centrifugo.consumers.consumer.Consumer.namespace`
and use local names in the decorator:

.. code-block:: python

   class StartResult(msgspec.Struct):
       started: str

   class HealthResult(msgspec.Struct):
       ok: bool

   class MessageConsumer(Consumer[MsgspecSerializationBackend]):
       namespace = "messages"

       @rpc("start")
       async def start(self, data: Message, context: RpcContext) -> StartResult:
           return StartResult(started=data.text)

       @rpc("health")
       async def health(self, data: Message, context: RpcContext) -> HealthResult:
           return HealthResult(ok=True)

This registers the RPC names ``messages.start`` and ``messages.health``. A nonempty
namespace is always prepended to every RPC name declared by the consumer. With
an empty namespace (the default), decorator names are used unchanged. The
namespace is inherited by subclasses. Decorator names must be unique within a
consumer; complete names must be unique across consumers.

The dot is part of the method name, not a Centrifugo RPC namespace separator. For instance, the
prefix ``chat:messages`` and local name ``start`` form
``chat:messages.start`` in Centrifugo's ``chat`` namespace.

For Pydantic, use a ``BaseModel`` and :class:`~django_centrifugo.plugins.pydantic.serializator.PydanticSerializationBackend`:

.. code-block:: python

   from pydantic import BaseModel
   from django_centrifugo.consumers import Consumer, rpc
   from django_centrifugo.contracts import RpcContext
   from django_centrifugo.plugins.pydantic.serializator import PydanticSerializationBackend

   class Message(BaseModel):
       text: str

   class SentMessage(BaseModel):
       user: str
       text: str

   class ChatConsumer(Consumer[PydanticSerializationBackend]):
       @rpc("chat:send")
       async def send_message(self, data: Message, context: RpcContext) -> SentMessage:
           return SentMessage(user=context.user, text=data.text)

Do not register both examples with the same name. The msgspec backend uses
strict conversion; Pydantic follows its model's configuration. Pydantic
validators receive the raw input as their validation context. The msgspec
backend's ``to_python`` supports JSON mode with aliases, but does not implement
``exclude_unset`` or Python mode. RPC methods return validated model results
under ``result.data``. A method returning ``None`` produces JSON ``null`` there.
Return annotations must be a supported model, ``Output[Model]``, an optional
supported model, or ``None``. Unsupported annotations fail during consumer
registration; invalid output is treated as an internal server error.
Server-initiated publications can use the HTTP SDK. RPC decorators do not
register connection lifecycle hooks.

Use :data:`~django_centrifugo.types.Output` when a method may return either a
model or a dictionary, so both forms are accepted by static type checkers:

.. code-block:: python

   from django_centrifugo.types import Output

   class ChatConsumer(Consumer[MsgspecSerializationBackend]):
       @rpc("chat:echo")
       async def echo(self, data: Message, context: RpcContext) -> Output[Message]:
           return {"text": data.text}

``Output[Message]`` is a type alias; the RPC dispatcher validates both returned
dictionaries and model instances against ``Message``. Invalid output is an
internal server error, rather than an input validation error.
Annotate a method that always returns a model with that model directly, or use
``None`` for a method that returns no application data.

Using the HTTP SDK in a consumer
--------------------------------

Set ``client`` in ``CENTRIFUGO_SETTINGS`` to configure a native
``cent.AsyncClient``. The mapping contains pycent constructor keyword arguments;
see :doc:`usage` for configuration and error handling:

.. code-block:: python

   CENTRIFUGO_SETTINGS = {
       "proxy_key": "load-the-proxy-key-from-your-secret-store",
       "consumers": ["myapp.actions.ChatConsumer"],
       "client": {
           "api_endpoint": "https://centrifugo.example.com/api",
           "api_key": "load-the-server-api-key-from-your-secret-store",
           "request_timeout": 5.0,
       },
   }

Access :attr:`~django_centrifugo.consumers.consumer.Consumer.centrifugo` in
actions and in ``on_subscribe``, ``on_stream_end``, or ``on_error``:

.. code-block:: python

   class ChatConsumer(Consumer[MsgspecSerializationBackend]):
       @rpc("chat:send")
       async def send_message(self, data: Message, context: RpcContext) -> None:
           await self.centrifugo.publish(channel="chat", data={"text": data.text})

The client is created on first access and reused for the lifetime of that
consumer instance. For an RPC, the framework closes it after the action and any
error hook finish; for a subscription, it remains available through the stream
end hook, then closes. A rejected subscription also closes its client after the
error hook. Do not close it yourself or retain it for background work beyond the
consumer's lifetime. Creation, use, and cleanup happen in the same event loop.
Results and exceptions are native pycent types. The SDK has its own API key,
separate from the incoming
proxy key. If ``client`` is omitted, consumers can handle incoming requests, but
accessing the property raises ``ImproperlyConfigured``.

Subscription streams
--------------------

Define a ``channel`` route with Django path converters. Its consumer must
implement ``on_subscribe`` to authorize the request; the default rejects it.
The ``data`` argument is validated using its annotation and the consumer's
serialization backend, as with RPC actions. The optional returned JSON object
is delivered in the subscription response.

.. code-block:: python

   import msgspec
   from django.core.exceptions import PermissionDenied
   from django_centrifugo.consumers import Consumer
   from django_centrifugo.contracts import SubscribeContext
   from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend

   class SubscriptionData(msgspec.Struct):
       language: str

   class RoomConsumer(Consumer[MsgspecSerializationBackend]):
       channel = "chat:room.<int:room_id>"

       async def on_subscribe(self, data: SubscriptionData, context: SubscribeContext) -> dict:
           if not await user_can_access_room(context.user, context.params["room_id"]):
               raise PermissionDenied
           return {"room_id": context.params["room_id"], "language": data.language}

       async def on_stream_end(self, context: SubscribeContext) -> None:
           await release_room_resources(context.client, context.params["room_id"])

For a Pydantic model, use the Pydantic serialization backend in the same way
as for an RPC action. Subscription payloads are JSON objects or ``null``;
an omitted payload is treated as ``None``. Use ``Model | None`` to accept
both a model and no data, or annotate ``data: None`` when no payload is expected.
Malformed JSON and non-object payloads are request errors; model validation
failures invoke ``on_error`` with ``PayloadValidationError`` before ``on_subscribe``
runs. A model with required fields rejects an omitted payload. The
:class:`~django_centrifugo.contracts.SubscribeContext` contains connection
metadata and channel parameters, not the payload.

The ``data`` and ``context`` arguments are passed by keyword.

One consumer can also handle several routes using
:attr:`~django_centrifugo.consumers.consumer.Consumer.channels`:

.. code-block:: python

   from collections.abc import Sequence
   from typing import ClassVar

   class RoomConsumer(Consumer[MsgspecSerializationBackend]):
       channels: ClassVar[Sequence[str]] = (
           "chat:room.<int:room_id>",
           "chat:events.<int:room_id>",
       )

       async def on_subscribe(self, data: None, context: SubscribeContext) -> dict:
           # Apply the application's authorization rules here.
           return {"channel": context.channel, "room_id": context.params["room_id"]}

``channel`` and ``channels`` may be used together; their routes are combined.
All routes use the same ``on_subscribe`` and payload annotation. Inspect
``context.channel`` and ``context.params`` to distinguish them. Route
configuration is read when the registry is built; later changes to a list do
not update a running server. Inherited routes are included without registering
the parent separately. Listing both classes with the same route is a conflict.

Routes must be unique; a channel matching more than one route fails closed,
including when both routes belong to the same consumer. A new consumer
instance is created for each stream; the same instance
receives both hooks. The stream-end hook runs after an accepted stream ends,
including cancellation and disconnect, but the reason is not available. It is
best-effort: crashes can prevent the hook from running. Design persistent
cleanup to be idempotent and recoverable. The stream does not keep history;
normal SDK publishing still broadcasts to channel subscribers.



Producing a stream
~~~~~~~~~~~~~~~~~~

Use :func:`~django_centrifugo.consumers.decorators.stream.stream` to register
an async generator for a channel. Loading the containing consumer registers the
route; it may also appear once in ``channel`` or ``channels``. Duplicate stream handlers
for a route are rejected. Matching different overlapping routes fails closed.
The same consumer instance and validated subscription data are passed to
``on_subscribe`` and, after authorization succeeds, to the generator.

.. code-block:: python

   from collections.abc import AsyncIterator
   import msgspec
   from django_centrifugo.consumers import Consumer, stream
   from django_centrifugo.contracts import SubscribeContext
   from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend
   from django_centrifugo.types import Output

   class RoomEvent(msgspec.Struct):
       room_id: int
       text: str

   class RoomConsumer(Consumer[MsgspecSerializationBackend]):
       async def on_subscribe(self, data: None, context: SubscribeContext) -> None:
           # Check the application's authorization rules here.
           return None

       @stream("chat:room.<int:room_id>")
       async def events(self, data: None, context: SubscribeContext) -> AsyncIterator[Output[RoomEvent]]:
           yield RoomEvent(room_id=context.params["room_id"], text="hello")
           yield {"room_id": context.params["room_id"], "text": "goodbye"}

Like ``@rpc``, the decorator creates an action descriptor. Each registry build
configures a separate :class:`~django_centrifugo.actions.stream.StreamAction`
for the route. Direct method calls on a consumer still invoke the original
generator; the configured action validates each output value. Both action
kinds share :class:`~django_centrifugo.actions.base.BaseAction`; the existing
RPC actions use :class:`~django_centrifugo.actions.rpc.RpcAction`.

Stream actions accept ``summary``, ``description``, ``tags`` and ``deprecated``
with the same semantics as RPC actions. Summary and description default to the
first paragraph and full docstring, respectively; tags are copied. Use
:func:`~django_centrifugo.consumers.registry.resolve_stream` with a concrete
channel name to inspect the configured action and its metadata:

.. code-block:: python

   from django_centrifugo.consumers import resolve_stream

   action = resolve_stream("chat:room.42")
   if action is not None:
       print(action.channel, action.summary, action.output_model)

It returns ``None`` for unknown channels and routes without a stream handler;
overlapping routes raise a configuration error. RPC actions remain available
through ``resolve_action`` in a separate name table within the same configured
registry.

Each value is validated against the yielded model and delivered as a
publication to this subscriber. SDK publications remain independent broadcasts.
Use ``AsyncIterator[RoomEvent]`` when yielding only model instances. The
selected backend validates dictionaries and model instances before sending;
after subscription acceptance an output or generator error terminates the gRPC
stream with an internal status and passes the exception to ``on_error``.
The returned proxy error cannot be sent after acceptance. Already sent events
cannot be recalled. A generator is closed when the subscription is cancelled.

By default ``close_on_complete=True`` closes the backend subscription stream
when the generator finishes. Centrifugo or the client may attempt to
resubscribe; application code should account for a new generator being started.
Use ``close_on_complete=False`` to keep the subscription open after the
last item, until disconnect or shutdown, including for normal SDK broadcasts.
This setting does not close a channel for other subscribers. The stream-end
hook runs after either kind of closure. Database connections are checked around
each generator iteration; application code should avoid holding connections
while waiting for external events inside a generator.

Custom backends implement :class:`~django_centrifugo.serialization.base.SerializationBackend`
and have a no-argument constructor. Their ``annotation`` parameters use
``TypeForm[Any]`` from ``typing_extensions`` to accept type expressions such as
``Model``, ``Model | None``, and ``Annotated[Model, ...]``. Payloads and validated
values use ``Any``. Their ``format_validation_error`` must
raise ``TypeError`` for unrelated exceptions. A backend's schema generator is
optional and is not used by RPC dispatch.

Error handling
--------------

Override :meth:`~django_centrifugo.consumers.consumer.Consumer.on_error` to
handle errors for a specific consumer. The hook runs on the same instance as
the RPC or subscription method and receives the original ``Exception``.
Returning a result stops error handling at the consumer level. Raise ``error``
to delegate to the global handler configured by ``error_handler``, or raise a
different exception to change what the global handler receives. The default
``on_error`` implementation raises the original exception.

Return :class:`~django_centrifugo.errors.ProxyError` to send a Centrifugo protocol
error in the response's ``error`` field. For RPC calls, any other serializable
result is sent as JSON in ``result.data``. The client SDK sees a successful RPC
response and application code interprets the domain error payload. Dictionaries
with fields named ``code`` or ``message`` are still domain data; only a
``ProxyError`` instance selects the protocol error path. Returning ``None`` sends
JSON null in ``result.data`` and does not invoke the global handler.

.. code-block:: python

   from django_centrifugo.consumers import Consumer
   from django_centrifugo.actions.errors import PayloadValidationError
   from django_centrifugo.errors import ProxyError
   from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend

   class ChatConsumer(Consumer[MsgspecSerializationBackend]):
       async def on_error(self, error: Exception):
           if isinstance(error, InsufficientBalance):
               return {"error": {"type": "insufficient_balance", "available": error.available}}
           if isinstance(error, PayloadValidationError):
               return ProxyError(1400, "Invalid message")
           raise error  # Delegate other errors to the global handler.

Here ``InsufficientBalance`` is an application-defined exception. Domain results
can be JSON-compatible values, msgspec structs, dataclasses, or models supported
by the selected RPC serialization backend, including models nested in containers.
They are serialized without validation against the RPC's success output model.
The backend configured for the action, including a decorator override, is used.

The hook handles failures after a consumer is selected, including RPC payload
validation, subscription setup, stream production, and ``on_stream_end``. Authentication failures
and errors before a consumer is selected do not invoke it. For ``on_stream_end``
the hook can perform side effects, but its return value cannot be sent to the
client because the stream has ended. Subscription refusals require ``ProxyError``;
a domain result during subscription setup is logged and replaced with the default
protocol error for the original exception, so it cannot accidentally accept a
subscription. If the global handler raises, or either handler returns an invalid
``ProxyError`` or an unserializable RPC result, the server uses a safe generic
internal error without invoking the handlers again.

For errors not handled by a consumer, set ``error_handler`` to a synchronous or
asynchronous callable or dotted import path. It receives the exception raised
by ``on_error``, or the original exception if no consumer was selected, and
follows the same return rules. ``None`` is sent as JSON null for RPC.
The setting defaults to :func:`~django_centrifugo.errors.default_error_handler`,
which maps request and validation exceptions to code 107 (bad request), unknown
actions to 104 (method not found), unknown channels to 102, and permission
exceptions to 103. Other exceptions use code 100 (internal server error) with
``temporary=True``. These are the built-in
`Centrifugo client error codes <https://centrifugal.dev/docs/server/codes#client-error-codes>`_.
``ProxyError`` accepts built-in codes 100–113 and custom codes 400–1999.
Codes reserved for unsubscribe or disconnect messages cannot be used here.
Never expose arbitrary exception messages or internal details to clients.

.. code-block:: python

   from django_centrifugo.errors import default_error_handler

   def handle_centrifugo_error(error):
       if isinstance(error, InsufficientBalance):
           return {"error": {"type": "insufficient_balance", "available": error.available}}
       return default_error_handler(error)

   CENTRIFUGO_SETTINGS = {
       "proxy_key": "load-from-secret-store",
       "consumers": ["myapp.actions.ChatConsumer"],
       "error_handler": "myapp.errors.handle_centrifugo_error",
   }
