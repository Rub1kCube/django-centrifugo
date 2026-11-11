Complete RPC and stream example
===============================

This example starts Centrifugo in Docker, runs the Django gRPC proxy on your
computer, calls an RPC, and receives stream events in a browser. The Django application is a single
Python file and serves a separate HTML file; Centrifugo uses its own
configuration and Compose file. Copy the four files below into the same empty
directory. It requires Python 3.12 or
newer, an environment with ``django-centrifugo`` installed, and Docker Compose.
Django, msgspec, and the gRPC dependencies are installed with the library.
Docker must support host networking: use Docker Engine on Linux, or Docker
Desktop 4.34 or newer with host networking enabled in its settings.

The example allows anonymous connections and uses public, fixed proxy and API keys.
It is intended for local development. For a real deployment, authenticate
clients, use a secret proxy key, restrict the gRPC listener and configure TLS
or a trusted network as described in :doc:`rpc-actions`.

1. Create the Django application
--------------------------------

Copy the entire application into a file:

.. literalinclude:: ../examples/quickstart.py
   :language: python
   :caption: :iconify:`devicon:python` example.py

The Python file configures Django, declares the RPC and stream, and serves the browser page.
The ``consumers`` setting points to ``GreetingConsumer`` in the running module
using ``f"{__name__}.GreetingConsumer"``. Its RPC and stream declarations are
validated and registered when the gRPC server is created.

The registered RPC name is ``greeting.hello``. The consumer's namespace is
joined to the local method name with a dot.

Place the browser page next to the Python file:

.. literalinclude:: ../examples/index.html
   :language: html
   :caption: :iconify:`devicon:html5` index.html

2. Configure Centrifugo
-----------------------

Configure the RPC and subscription stream proxies:

.. code-block:: json
   :caption: :iconify:`devicon:json` config.json

   {
     "http_server": {
       "address": "127.0.0.1"
     },
     "http_api": {
       "key": "local-api-example-key"
     },
     "client": {
       "allowed_origins": ["http://localhost:8080", "http://127.0.0.1:8080"],
       "allow_anonymous_connect_without_token": true
     },
     "channel": {
       "proxy": {
         "subscribe_stream": {
           "endpoint": "grpc://127.0.0.1:10000",
           "grpc": {
             "static_metadata": {
               "x-centrifugo-proxy-key": "local-proxy-example-key"
             }
           }
         }
       },
       "namespaces": [
         {"name": "chat", "subscribe_stream_proxy_enabled": true}
       ]
     },
     "rpc": {
       "proxy": {
         "endpoint": "grpc://127.0.0.1:10000",
         "grpc": {
           "static_metadata": {
             "x-centrifugo-proxy-key": "local-proxy-example-key"
           }
         }
       },
       "without_namespace": {
         "proxy_enabled": true
       }
     }
   }

The proxy key must match ``CENTRIFUGO_SETTINGS['proxy_key']``, and the HTTP API
key must match ``CENTRIFUGO_SETTINGS['client']['api_key']``. Centrifugo uses
``:`` to separate its RPC namespaces; ``greeting.hello`` contains no colon,
so it uses ``without_namespace``.

Run Centrifugo with Docker Compose:

.. code-block:: yaml
   :caption: :iconify:`devicon:docker` compose.yaml

   services:
     centrifugo:
       image: centrifugo/centrifugo:v6.10.0
       command: centrifugo -c /centrifugo/config.json
       network_mode: host
       volumes:
         - ./config.json:/centrifugo/config.json:ro

Host networking lets Centrifugo connect to the local Django proxy at
``127.0.0.1:10000``. Centrifugo listens on ``127.0.0.1:8000`` rather than
publishing a Docker port. Both ports must be available on the host.

3. Run the example
------------------

From the directory containing the four files, start Centrifugo in one terminal:

.. code-block:: console

   docker compose up

In a second terminal, start the Django proxy using the Python environment where
the library is installed. It checks the HTTP API and prints the node information
before starting the gRPC listener:

.. code-block:: console

   python example.py runcentrifugogrpc --address 127.0.0.1:10000

In a third terminal, start Django to serve the browser page:

.. code-block:: console

   python example.py runserver 127.0.0.1:8080

Open ``http://localhost:8080`` or ``http://127.0.0.1:8080``. The page should display:

.. code-block:: json

   {
     "message": "Hello, World!"
   }

The request travels from the browser to Centrifugo over WebSocket, then from
Centrifugo to Django over gRPC. The RPC validates the incoming dictionary as a
``Greeting`` and returns the result along the same path. The browser also
subscribes to ``chat:room.1``; the stream sends five room events, two seconds
apart, and the page displays the latest one. Each event contains the room ID,
the requested language, and a sequence number. The subscription remains open
after the final event until the browser disconnects. Stop each process with
Ctrl+C when finished.

The consumer's ``on_error`` hook returns a client-safe error object for invalid
payloads and unexpected errors, and logs the details of unexpected exceptions.
Errors during RPC or subscription setup can be sent to the client. If the
generator fails after the subscription has been accepted, the stream ends and
the hook's returned object cannot be delivered as a publication. See
:doc:`rpc-actions` for details.
