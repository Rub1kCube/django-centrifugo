"""HTTP integration for authenticating Centrifugo connections."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any, override

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseForbidden, JsonResponse
from django.utils.cache import patch_cache_control
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from django_centrifugo.settings import Settings, resolve_setting


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def _connect_secret() -> str:
    secret: str = resolve_setting(Settings.connect_secret)
    if not secret.strip():
        msg = "CENTRIFUGO_SETTINGS['connect_secret'] must be a nonempty string for the connect view"
        raise ImproperlyConfigured(msg)
    return secret


def _response(data: dict[str, Any]) -> JsonResponse:
    response = JsonResponse(data)
    patch_cache_control(response, no_store=True, private=True)
    return response


@method_decorator(csrf_exempt, name="dispatch")
class CentrifugoConnectView(View):
    """Authenticate an HTTP connect proxy request using Django's current session.

    Register this view explicitly in the application's URL configuration. The
    caller must provide the configured ``connect_secret`` in the
    ``X-Centrifugo-Connect-Secret`` header. Django's session and authentication
    middleware must set ``request.user``. Anonymous and inactive users are
    rejected; successful responses contain their string primary key.

    The view is CSRF-exempt because Centrifugo sends the POST server-to-server;
    protect the shared secret, the network path, and the WebSocket origin.
    Authentication is checked at connection time only.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If the secret is missing or
            authentication middleware has not set ``request.user``.
    """

    http_method_names: Sequence[str] = ("post",)

    @classmethod
    @override
    def as_view(cls, **initkwargs: Any) -> Callable[..., HttpResponseBase]:
        """Validate the required secret when the endpoint is registered.

        Raises:
            django.core.exceptions.ImproperlyConfigured: If the secret is missing.
        """
        _connect_secret()
        return super().as_view(**initkwargs)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Return a Centrifugo connection result for an authenticated session.

        Args:
            request: Connect proxy request with the shared secret header.

        Returns:
            A Centrifugo result or error response. An invalid proxy secret
            receives HTTP 403.

        Raises:
            django.core.exceptions.ImproperlyConfigured: If the secret is missing
                or authentication middleware is not configured.
        """
        expected = _connect_secret()
        supplied = request.headers.get("X-Centrifugo-Connect-Secret", "")
        if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            return HttpResponseForbidden()

        user = getattr(request, "user", None)
        if user is None:
            msg = "CentrifugoConnectView requires Django AuthenticationMiddleware"
            raise ImproperlyConfigured(msg)
        if not user.is_authenticated or not getattr(user, "is_active", True) or user.pk is None or not str(user.pk):
            return _response({"error": {"code": 403, "message": "Authentication required"}})
        return _response({"result": {"user": str(user.pk)}})
