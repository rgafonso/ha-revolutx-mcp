"""Connect-URL helpers shared by the options flow and integration setup."""
from __future__ import annotations

from urllib.parse import urlparse

from homeassistant.components import webhook
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url


def webhook_connect_url(hass: HomeAssistant, webhook_id: str) -> str:
    return webhook.async_generate_url(hass, webhook_id)


def direct_connect_url(hass: HomeAssistant, port: int, path_secret: str) -> str:
    """Best-effort LAN URL for the direct-port server, for display only."""
    try:
        base = get_url(hass, allow_internal=True, allow_external=False, prefer_external=False)
        host = urlparse(base).hostname or "<your-ha-ip>"
    except NoURLAvailableError:
        host = "<your-ha-ip>"
    return f"http://{host}:{port}/{path_secret}"
