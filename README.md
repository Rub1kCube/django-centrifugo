# django-centrifugo

A Django integration for [Centrifugo](https://centrifugal.dev/). Define async RPC
handlers and subscription streams, publish messages through the HTTP API, and
authenticate connections with Django sessions.

Requires Python 3.12+, Django 5.2, and Centrifugo 6+.

## Installation

```bash
pip install django-centrifugo
```

Add the application and configure a secret shared with the Centrifugo gRPC
proxy. List dotted paths to the consumer classes enabled when the server starts:

```python
# settings.py
import os

INSTALLED_APPS = [
    # ...
    "django_centrifugo",
]

CENTRIFUGO_SETTINGS = {
    "proxy_key": os.environ["CENTRIFUGO_PROXY_KEY"],
    "consumers": ["myapp.centrifugo.GreetingConsumer"],
}
```

## RPC and streams

```python
# myapp/centrifugo.py
import msgspec

from django_centrifugo.consumers import Consumer, rpc
from django_centrifugo.contracts import RpcContext
from django_centrifugo.plugins.msgspec.serializator import MsgspecSerializationBackend


class Greeting(msgspec.Struct):
    name: str


class GreetingResult(msgspec.Struct):
    message: str


class GreetingConsumer(Consumer[MsgspecSerializationBackend]):
    namespace = "greeting"

    @rpc("hello")
    async def hello(self, data: Greeting, context: RpcContext) -> GreetingResult:
        return GreetingResult(message=f"Hello, {data.name}!")
```

Run the proxy as a separate process:

```bash
python manage.py runcentrifugogrpc --address 127.0.0.1:10000
```

Configure Centrifugo to proxy RPC requests to this address and send the same
`proxy_key` in `x-centrifugo-proxy-key` gRPC metadata. The method name is
`greeting.hello`. Authentication and permissions for RPC methods are the
application's responsibility.

For a complete runnable example with Centrifugo, a browser client, and a
subscription stream, see the [quickstart](docs/pages/quickstart.rst). More
information on configuration, access control, and stream lifecycle is in the
[RPC and streams guide](docs/pages/rpc-actions.rst).

## Publish a message

Configure pycent once in Django settings:

```python
import os

CENTRIFUGO_SETTINGS = {
    # ...
    "client": {
        "api_endpoint": "https://centrifugo.example.com/api",
        "api_key": os.environ["CENTRIFUGO_API_KEY"],
    },
}
```

Then publish without managing an SDK client directly:

```python
from django_centrifugo.shortcuts import publish

publish("announcements:all", {"message": "Hello!"})
```

Use `await apublish(...)` from asynchronous code:

```python
from django_centrifugo.shortcuts import apublish

await apublish("announcements:all", {"message": "Hello!"})
```

Send the same message to several channels with `broadcast` or `abroadcast`:

```python
from django_centrifugo.shortcuts import abroadcast, broadcast

broadcast(["user:1", "user:2"], {"message": "Hello!"})
await abroadcast(["user:1", "user:2"], {"message": "Hello!"})
```

Use `create_client()` or `create_async_client()` from `django_centrifugo.clients`
to reuse a native [pycent](https://github.com/centrifugal/pycent) client across calls.
Results and exceptions come directly from `cent`. See the [usage guide](docs/pages/usage.rst). Client access to channels must be
configured in Centrifugo; publishing alone does not grant subscription access or
guarantee delivery to offline users.

## Session authentication

The optional `CentrifugoConnectView` authenticates a Centrifugo HTTP connect
proxy using Django sessions. It must be registered explicitly and configured
with its own `connect_secret`. See the [session authentication guide](docs/pages/session-authentication.rst)
for cookie, secret, origin, and connection-lifetime requirements.

## AsyncAPI documentation

AsyncAPI documentation generation for RPC methods and subscription streams is
planned. Schema export and a documentation UI are not yet available in this release.

## Documentation and development

The [documentation](docs/index.rst) contains the full guides and API reference.
From the repository root, use `just install` to set up the development
environment and `just check-all` to run the project checks. See
[CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

[MIT](LICENSE).
