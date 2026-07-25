"""The Revolut X MCP integration: read-only Revolut X market/account data exposed
as MCP tools, reachable via a Home Assistant webhook and/or a standalone direct-port
server."""
from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.network import get_url

from .const import (
    AUTH_MODE_LEGACY_OAUTH,
    CONF_API_KEY,
    CONF_AUTH_MODE,
    CONF_DIRECT_SERVER_ENABLED,
    CONF_DIRECT_SERVER_PORT,
    CONF_DIRECT_SERVER_SECRET,
    CONF_EXTERNAL_URL,
    CONF_OAUTH_SIGNING_KEY,
    CONF_PRIVATE_KEY,
    CONF_TRADING_ENABLED,
    CONF_WEBHOOK_ID,
    DEFAULT_AUTH_MODE,
    DEFAULT_DIRECT_SERVER_ENABLED,
    DEFAULT_DIRECT_SERVER_PORT,
    DEFAULT_TRADING_ENABLED,
    DOMAIN,
)
from .coordinator import RevolutXDataUpdateCoordinator
from .direct_server import DirectServer
from .oauth_legacy import async_register_views, issuer_url, webhook_resource_metadata_url
from .revolut_client import RevolutXClient, load_private_key
from .transport import RequestStats, request_served_signal
from .urls import direct_connect_url, webhook_connect_url
from .webhook import async_register_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

# Legacy-OAuth HTTP views (/authorize, /token, /.well-known/*) are registered once,
# globally, on Home Assistant's own HTTP app — not once per config entry. This
# integration is designed for a single Revolut X account per HA instance; if a
# second config entry also enables legacy_oauth, its requests are validated with
# the *first* entry's signing key (a logged, documented limitation, not a crash).
_OAUTH_VIEWS_KEY = f"{DOMAIN}_oauth_views_registered"


class RuntimeData:
    """Per-config-entry runtime objects, stored in hass.data."""

    def __init__(
        self,
        client: RevolutXClient,
        direct_server: DirectServer,
        coordinator: RevolutXDataUpdateCoordinator,
        stats: RequestStats,
    ) -> None:
        self.client = client
        self.direct_server = direct_server
        self.coordinator = coordinator
        self.stats = stats


def _base_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    external = entry.options.get(CONF_EXTERNAL_URL)
    if external:
        return external.rstrip("/")
    return get_url(hass, prefer_external=True)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = aiohttp_client.async_get_clientsession(hass)
    private_key = load_private_key(entry.data[CONF_PRIVATE_KEY])
    client = RevolutXClient(session, entry.data[CONF_API_KEY], private_key, hass=hass)

    auth_mode = entry.options.get(CONF_AUTH_MODE, DEFAULT_AUTH_MODE)
    trading_enabled = entry.options.get(CONF_TRADING_ENABLED, DEFAULT_TRADING_ENABLED)
    signing_key = bytes.fromhex(entry.data[CONF_OAUTH_SIGNING_KEY])
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    base = _base_url(hass, entry)

    stats = RequestStats(signal=request_served_signal(entry.entry_id))

    webhook_resource_metadata = (
        webhook_resource_metadata_url(base, webhook_id)
        if auth_mode == AUTH_MODE_LEGACY_OAUTH
        else None
    )
    async_register_webhook(
        hass,
        webhook_id,
        client,
        auth_mode,
        signing_key,
        trading_enabled=trading_enabled,
        resource_metadata_url=webhook_resource_metadata,
        stats=stats,
    )

    if auth_mode == AUTH_MODE_LEGACY_OAUTH:
        if hass.data.get(_OAUTH_VIEWS_KEY):
            _LOGGER.warning(
                "Legacy OAuth views are already registered by another Revolut X MCP "
                "entry; this entry's tokens will be validated with that entry's "
                "signing key."
            )
        else:
            async_register_views(hass, signing_key, lambda: _base_url(hass, entry))
            hass.data[_OAUTH_VIEWS_KEY] = True

    direct_server = DirectServer()
    if entry.options.get(CONF_DIRECT_SERVER_ENABLED, DEFAULT_DIRECT_SERVER_ENABLED):
        port = entry.options.get(CONF_DIRECT_SERVER_PORT, DEFAULT_DIRECT_SERVER_PORT)
        path_secret = entry.data[CONF_DIRECT_SERVER_SECRET]
        issuer = issuer_url(base) if auth_mode == AUTH_MODE_LEGACY_OAUTH else None
        try:
            await direct_server.async_start(
                hass,
                port,
                path_secret,
                client,
                auth_mode,
                signing_key,
                trading_enabled=trading_enabled,
                issuer=issuer,
                stats=stats,
            )
        except OSError as err:
            async_unregister_webhook(hass, webhook_id)
            raise ConfigEntryNotReady(
                f"Could not bind Revolut X MCP direct server to port {port}"
            ) from err

    coordinator = RevolutXDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = RuntimeData(
        client, direct_server, coordinator, stats
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _notify_connect_urls(hass, entry)
    return True


def _notify_connect_urls(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Log and surface (via a persistent notification) the URL(s) to paste into an
    MCP client — otherwise there's no way to find them without reading the source."""
    webhook_url = webhook_connect_url(hass, entry.data[CONF_WEBHOOK_ID])
    lines = [f"Webhook URL: {webhook_url}"]

    if entry.options.get(CONF_DIRECT_SERVER_ENABLED, DEFAULT_DIRECT_SERVER_ENABLED):
        direct_url = direct_connect_url(
            hass,
            entry.options.get(CONF_DIRECT_SERVER_PORT, DEFAULT_DIRECT_SERVER_PORT),
            entry.data[CONF_DIRECT_SERVER_SECRET],
        )
        lines.append(f"Direct URL: {direct_url}")

    message = "\n\n".join(lines)
    _LOGGER.info("Revolut X MCP server started. %s", message.replace("\n\n", " | "))
    persistent_notification.async_create(
        hass,
        f"Revolut X MCP server started. Paste one of these into your AI client:\n\n{message}",
        title="Revolut X MCP",
        notification_id=f"{DOMAIN}_{entry.entry_id}_connect_url",
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    runtime: RuntimeData = hass.data[DOMAIN].pop(entry.entry_id)
    async_unregister_webhook(hass, entry.data[CONF_WEBHOOK_ID])
    await runtime.direct_server.async_stop()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed (auth mode, port, ...) — reload the entry to apply them."""
    await hass.config_entries.async_reload(entry.entry_id)
