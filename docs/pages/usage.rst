Usage
=====

The server API uses `pycent <https://github.com/centrifugal/pycent/tree/v6.0.0>`_
(the ``cent`` package). Configure its constructor keyword arguments in
``CENTRIFUGO_SETTINGS['client']``:

.. code-block:: python
   :caption: :iconify:`devicon:python` settings.py

   CENTRIFUGO_SETTINGS = {
       "client": {
           "api_endpoint": "https://centrifugo.example.com/api",
           "api_key": "your-server-api-key",
           "request_timeout": 5.0,
       },
   }

``api_endpoint`` is the full HTTP API address, including any reverse-proxy path
and the API prefix. The integration passes the mapping to ``cent.Client`` or
``cent.AsyncClient``; pycent validates constructor options. Invalid or missing
configuration raises ``django.core.exceptions.ImproperlyConfigured`` when a
client is requested. Configuration is optional for applications that only handle
incoming proxy requests. Django setting changes invalidate cached configuration;
clients already created keep their own configuration.

Publishing shortcuts
--------------------

Use :func:`~django_centrifugo.shortcuts.publish` from synchronous code:

.. code-block:: python

   from django_centrifugo.shortcuts import publish

   result = publish("chat", {"text": "Hello!"}, idempotency_key="message-42")
   print(result.offset, result.epoch)

Use :func:`~django_centrifugo.shortcuts.apublish` from asynchronous code:

.. code-block:: python

   from django_centrifugo.shortcuts import apublish

   async def send_message():
       return await apublish("chat", {"text": "Hello!"}, timeout=2.0)

Each shortcut creates and closes its client for the call. Both accept pycent's
publication options, including JSON or base64 payloads, tags, idempotency keys,
and a per-call timeout. Results are native ``cent.PublishResult`` objects.
Payload handling, validation, and exceptions follow pycent.

To send the same publication to multiple channels, use
:func:`~django_centrifugo.shortcuts.broadcast` or
:func:`~django_centrifugo.shortcuts.abroadcast`:

.. code-block:: python

   from django_centrifugo.shortcuts import abroadcast, broadcast

   result = broadcast(["user:1", "user:2"], {"text": "Hello!"})

   async def notify_users():
       return await abroadcast(["user:1", "user:2"], {"text": "Hello!"}, timeout=2.0)

These shortcuts accept the same publication options and manage their clients
in the same way. They return native ``cent.BroadcastResult`` objects with an
outcome for each channel. If any channel fails, pycent raises
``cent.BroadcastFailedChannelsError`` with the complete result; broadcasts are
not atomic.

Reusing a client
----------------

For a series of calls, create one native client with
:func:`~django_centrifugo.clients.create_client` and reuse its HTTP connections.
The caller owns each client returned by a factory and must close it:

.. code-block:: python

   from django_centrifugo.clients import create_client

   with create_client() as client:
       first = client.publish(channel="chat", data={"text": "Hello!"})
       second = client.publish(channel="chat", data={"text": "Another message"})
       history = client.history(channel="chat", limit=10)

For asynchronous code, use :func:`~django_centrifugo.clients.create_async_client`
inside the event loop where the client will run:

.. code-block:: python

   from django_centrifugo.clients import create_async_client

   async def send_messages():
       async with create_async_client() as client:
           await client.publish(channel="chat", data={"text": "Hello!"})
           await client.publish(channel="chat", data={"text": "Another message"})

Factories create new instances rather than returning a shared client. An
asynchronous client must be created, used, and closed in the same event loop;
do not share it across separate ``asyncio.run()`` calls. When supplying an
``http_client`` option, use ``httpx2.Client`` for synchronous calls or
``httpx2.AsyncClient`` for asynchronous calls. The supplied HTTP client remains
owned by the caller and must be closed separately.

For use without Django settings, instantiate ``cent.Client`` or
``cent.AsyncClient`` directly. All server API methods and their types are
available through pycent; see its
`API reference <https://github.com/centrifugal/pycent/blob/v6.0.0/API.md>`_.
For publishing inside a consumer, see :doc:`rpc-actions`.

Errors and retries
------------------

Calls return pycent dataclasses and raise pycent exceptions, whose base is
``cent.CentError``. For example, a server API failure raises ``cent.ApiError``
or one of its subclasses; a timeout raises ``cent.CentTimeoutError``.
The integration does not translate these errors or add automatic retries.

A failed request can have taken effect on the server. For explicit publication
retries, reuse the same ``idempotency_key`` for the same message when the broker
supports deduplication. Use pycent's retry facilities when needed.

Broadcast and batch
-------------------

``broadcast`` raises ``cent.BroadcastFailedChannelsError`` when any channel
fails; the exception retains the complete result. A batch raises
``cent.BatchFailedCommandsError`` when any command fails, with individual
results still available. These operations are not atomic.

.. code-block:: python

   import cent
   from django_centrifugo.clients import create_client

   with create_client() as client:
       try:
           client.broadcast(channels=["user:1", "user:2"], data={"text": "Hello!"})
       except cent.BroadcastFailedChannelsError as error:
           print(error.failed)

       batch = client.new_batch()
       publication = batch.publish(channel="chat", data={"text": "Hello!"})
       stats = batch.presence_stats(channel="chat")
       try:
           batch.send()
       except cent.BatchFailedCommandsError as error:
           print(error.failed)
       else:
           print(publication.result().offset)
           print(stats.result().num_clients)

Presence and history require the corresponding channel features to be enabled.

Package metadata
----------------

The installed package exposes its version metadata:

.. doctest::

   >>> from django_centrifugo.__metadata__ import __version__
   >>> isinstance(__version__, str)
   True
