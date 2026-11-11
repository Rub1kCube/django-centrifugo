Authenticate connections with Django sessions
=============================================

:class:`~django_centrifugo.http.CentrifugoConnectView` is an optional HTTP
connect proxy for applications using Django sessions. Centrifugo forwards the
browser's session cookie to this view when a client connects without a
connection JWT. Django resolves the session using its usual authentication
middleware; the view returns the user's primary key as Centrifugo's user ID.
This establishes identity only. Application code remains responsible for any
permissions on RPC calls and channel subscriptions.

1. Configure Django
-------------------

Install and configure Django authentication and sessions, including
``django.contrib.sessions.middleware.SessionMiddleware`` and
``django.contrib.auth.middleware.AuthenticationMiddleware`` in that order.
Both Django and Centrifugo's connect endpoint must use the same session store.
Django's regular session authentication backend is responsible for validating
sessions and users.

Set a long random secret specifically for the HTTP connect endpoint. It must be
separate from the gRPC proxy key, the Centrifugo HTTP API key, Django's secret
key, and JWT signing keys:

.. code-block:: python
   :caption: :iconify:`devicon:python` settings.py

   import os

   CENTRIFUGO_SETTINGS = {
       "proxy_key": os.environ["CENTRIFUGO_GRPC_PROXY_KEY"],
       "connect_secret": os.environ["CENTRIFUGO_CONNECT_SECRET"],
   }

Register the endpoint explicitly. Calling ``as_view()`` validates that the
secret is a nonempty string; a missing, blank, or invalid secret raises
``ImproperlyConfigured`` when the URL configuration is loaded. The view also
checks the current setting on every request, so secret rotation through a
Django settings change takes effect without retaining the previous secret.

.. code-block:: python
   :caption: :iconify:`devicon:python` urls.py

   from django.urls import path
   from django_centrifugo.http import CentrifugoConnectView

   urlpatterns = [
       path("centrifugo/connect/", CentrifugoConnectView.as_view()),
   ]

2. Configure Centrifugo
-----------------------

Add the following to the existing Centrifugo configuration, replacing the
addresses and secret with your deployment's values. The endpoint address is
where Centrifugo can reach Django; the allowed origin is the browser page's
origin. Set the connect secret from a secret store rather than committing it.

.. code-block:: json
   :caption: :iconify:`devicon:json` config.json

   {
     "client": {
       "allowed_origins": ["https://app.example.com"],
       "proxy": {
         "connect": {
           "enabled": true,
           "endpoint": "http://django:8000/centrifugo/connect/",
           "http_headers": ["Cookie"],
           "http": {
             "static_headers": {
               "X-Centrifugo-Connect-Secret": "replace-from-secret-store"
             }
           }
         }
       }
     }
   }

The header value must match ``connect_secret`` exactly. Never allowlist
``X-Centrifugo-Connect-Secret`` in ``http_headers`` or ``emulated_headers``:
client-supplied headers can override static headers. Protect the HTTP route from
external access where possible, and use TLS or an appropriately protected
network for all traffic carrying session cookies and proxy secrets. Do not
log cookies or secrets. Configure ``allowed_origins`` narrowly to prevent
cross-site WebSocket hijacking; origin checks are not authentication for
non-browser clients. The view is CSRF-exempt because it receives a
server-to-server POST, and validates the proxy secret instead.

The browser must send its session cookie to Centrifugo during the connection
request. A common arrangement puts Django and Centrifugo behind the same host,
with the reverse proxy routing the WebSocket path to Centrifugo. Cookie domain,
path, ``Secure`` and ``SameSite`` attributes and browser third-party-cookie
policies determine whether the browser sends it. Use HTTPS/WSS and appropriate
``SESSION_COOKIE_SECURE`` and ``SESSION_COOKIE_HTTPONLY`` settings.

3. Handle connection identity
-----------------------------

With a valid proxy secret and authenticated, active Django user, the view returns
``{"result": {"user": "42"}}`` for a user with primary key ``42``. An anonymous,
inactive, or unsaved user receives a Centrifugo protocol error with code 403.
A missing or invalid proxy secret receives HTTP 403. If authentication middleware
is missing, the view raises ``ImproperlyConfigured`` rather than accepting an
anonymous connection. Responses containing a result or protocol error use
``Cache-Control: no-store, private``.

Centrifugo forwards the user ID in subsequent RPC and stream proxy requests;
:meth:`~django_centrifugo.consumers.consumer.Consumer.on_subscribe` and RPC
methods receive it in ``context.user``. The view does not load a Django user
object for those gRPC methods, and does not enforce permissions.

The connect proxy authenticates at connection time, not continuously. Logging
out of Django or deactivating a user does not automatically disconnect existing
Centrifugo connections. If immediate revocation is required, the application
must explicitly disconnect the user through the Centrifugo API or implement
an appropriate connection expiration and refresh policy.

Connection JWTs are an independent authentication path: when Centrifugo
accepts a client-provided JWT, connect proxy is not called. Configure all
allowed authentication paths deliberately; this view cannot enforce session
checks on connections authenticated through another path. Subscription tokens
and user-limited channels can likewise bypass subscribe-stream proxy, so they
should not be used where every subscription must run the application's stream.
