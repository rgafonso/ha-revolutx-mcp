"""Webhook transport: registers with Home Assistant's `webhook` component so MCP
clients can reach this integration through HA's own HTTP endpoint (works through
Nabu Casa remote access or any reverse proxy already pointed at Home Assistant).

By default (auth mode "none") the webhook_id embedded in the URL is itself the
credential, matching `homeassistant.components.webhook`'s default posture
(`requires_auth = False` on the underlying view). When auth mode is "legacy_oauth"
or "ha_auth", a bearer token is also required — see `transport.handle_mcp_http`.
"""
from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SERVER_NAME
from .revolut_client import RevolutXClient
from .transport import handle_mcp_http

_LOGGER = logging.getLogger(__name__)


def async_register_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    client: RevolutXClient,
    auth_mode: str,
    signing_key: bytes,
    trading_enabled: bool = False,
    resource_metadata_url: str | None = None,
) -> None:
    async def _handler(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        return await handle_mcp_http(
            request, client, auth_mode, signing_key, hass, trading_enabled, resource_metadata_url
        )

    webhook.async_register(hass, DOMAIN, SERVER_NAME, webhook_id, _handler)


def async_unregister_webhook(hass: HomeAssistant, webhook_id: str) -> None:
    webhook.async_unregister(hass, webhook_id)
