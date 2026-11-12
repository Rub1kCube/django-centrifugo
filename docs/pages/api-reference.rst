API reference
=============

Package
-------

.. automodule:: django_centrifugo
   :members:
   :show-inheritance:

Metadata
--------

.. automodule:: django_centrifugo.__metadata__
   :members:

Django shortcuts
----------------

.. automodule:: django_centrifugo.shortcuts
   :members:

Server API clients
------------------

The factories return native pycent clients. Results and exceptions are defined
by ``cent``; see :doc:`usage` for configuration and lifecycle.

.. automodule:: django_centrifugo.clients
   :members:

HTTP connect proxy
------------------

.. automodule:: django_centrifugo.http
   :members:

RPC actions
-----------

Consumers are enabled through dotted class paths in
``CENTRIFUGO_SETTINGS['consumers']``. See :doc:`rpc-actions` for configuration,
validation timing, and registry snapshots used by running servers.
RPC and stream actions share the abstract
:class:`~django_centrifugo.actions.base.BaseAction` registration contract while
retaining their separate execution and output validation behavior.

.. automodule:: django_centrifugo.consumers.consumer
   :members:

.. automodule:: django_centrifugo.consumers.decorators

.. automodule:: django_centrifugo.consumers.decorators.rpc
   :members:

.. automodule:: django_centrifugo.consumers.decorators.stream
   :members:

.. automodule:: django_centrifugo.actions

.. automodule:: django_centrifugo.consumers.registry
   :members: resolve_stream

Consumer metadata
~~~~~~~~~~~~~~~~~

The internal consumer registry exposes ``describe(consumers=None)`` for schema
generators. It returns an immutable
:class:`~django_centrifugo.consumers.metadata.ApplicationMetadata` snapshot of
configured contracts without inspecting handlers again or executing them.
``None`` selects all registered consumers; an empty sequence selects none.
Explicit selections must contain registered classes, including consumers without
actions. Results preserve registration order and include duplicate selections
once. An unregistered class raises ``ImproperlyConfigured``.

RPC metadata contains the effective serialization backend, resolved input
annotation, and validated output annotation. ``Output[T]`` becomes ``T``;
an RPC returning ``None`` has ``NoneType`` as its output annotation. Subscription
inputs come from the configured ``on_subscribe`` contract. Routes retain their
original spelling, expose addresses with ``{parameter}`` placeholders, and list
converter names and matching patterns. A channel without a stream has no inferred
publication contract. Python annotations retain ``Annotated`` metadata; JSON
schemas are generated separately.

Each call returns a fresh snapshot. Changing ``CENTRIFUGO_SETTINGS`` invalidates
the configured registry for subsequent lookups; previously obtained registries
and metadata snapshots remain usable.

.. automodule:: django_centrifugo.consumers.metadata
   :members:

Action contracts
~~~~~~~~~~~~~~~~

.. automodule:: django_centrifugo.actions.base
   :members:

.. automodule:: django_centrifugo.actions.stream
   :members:

.. automodule:: django_centrifugo.actions.rpc
   :members:

.. automodule:: django_centrifugo.actions.errors
   :members:

.. automodule:: django_centrifugo.actions.registry
   :members:

.. automodule:: django_centrifugo.contracts
   :members:

.. automodule:: django_centrifugo.types

.. autodata:: django_centrifugo.types.Output
   :no-value:

.. automodule:: django_centrifugo.errors
   :members:

.. automodule:: django_centrifugo.grpc.server
   :members:

.. automodule:: django_centrifugo.grpc.runner
   :members:

.. automodule:: django_centrifugo.serialization.errors
   :members:

.. automodule:: django_centrifugo.serialization.base
   :members:

.. automodule:: django_centrifugo.plugins.msgspec.serializator
   :members:

.. automodule:: django_centrifugo.plugins.pydantic.serializator
   :members:

.. automodule:: django_centrifugo.settings

.. automodule:: django_centrifugo.settings.keys
   :members:

.. automodule:: django_centrifugo.settings.resolver
   :members: resolve_setting, clear_settings_cache

Type inspection
---------------

Inspect a standalone function without a class. Pass a concrete class when
annotations need its namespace or inherited generic type bindings, using
``MethodSignature.from_method(MyClass.method, target_class=MyClass)``.
The signature and selected annotations come from the callable's public signature,
including a wrapper's explicit ``__signature__``. Wrapped methods provide the
declaring class and the namespace for annotations copied from the original.
Call :meth:`~django_centrifugo.utils.type_inspection.signatures.MethodSignature.clear_cache`
after changing a callable's signature, annotations, or relevant namespaces.

.. doctest::

   >>> from django_centrifugo.utils.type_inspection import MethodSignature
   >>> def identity(value: str) -> str:
   ...     return value
   >>> result = MethodSignature.from_method(identity)
   >>> result.annotations["return"] is str
   True
   >>> dict(result.bindings)
   {}

.. automodule:: django_centrifugo.utils.type_inspection.signatures
   :members: MethodSignature
