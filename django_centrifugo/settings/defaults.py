from typing import Any

from django_centrifugo.settings.keys import Settings


DEFAULT_SETTINGS: dict[Settings, Any] = {
    Settings.proxy_key: "",
    Settings.connect_secret: "",
    Settings.error_handler: None,
    Settings.consumers: (),
    Settings.client: None,
}
"""Default values for all integration settings."""
