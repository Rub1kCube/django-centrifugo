from typing import Any

from django_centrifugo.errors import default_error_handler
from django_centrifugo.settings.keys import Settings


DEFAULT_SETTINGS: dict[Settings, Any] = {
    Settings.proxy_key: "",
    Settings.connect_secret: "",
    Settings.error_handler: default_error_handler,
    Settings.consumers: (),
    Settings.client: None,
}
"""Default values for all integration settings."""
