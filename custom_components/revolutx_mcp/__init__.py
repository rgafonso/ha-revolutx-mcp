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
    CONF_AUTO_RESUME,
    CONF_DIRECT_SERVER_ENABLED,
    CONF_DIRECT_SERVER_PORT,
    CONF_DIRECT_SERVER_SECRET,
    CONF_EXTERNAL_URL,
    CONF_OAUTH_SIGNING_KEY,
    CONF_PRIVATE_KEY,
    CONF_TRADING_ENABLED,
    CONF_WEBHOOK_ID,
    DEFAULT_AUTH_MODE,
    DEFAULT_AUTO_RESUME,
    DEFAULT_DIRECT_SERVER_ENABLED,
    DEFAULT_DIRECT_SERVER_PORT,
    DEFAULT_TRADING_ENABLED,
    DOMAIN,
    SUBENTRY_TYPE_GRID_BOT,
)
from .alert_coordinator import RevolutXAlertCoordinator
from .coordinator import RevolutXDataUpdateCoordinator
from .direct_server import DirectServer
from .grid_bot import GridBotEngine
from .oauth_legacy import async_register_views, issuer_url, webhook_resource_metadata_url
from .revolut_client import RevolutXClient, load_private_key
from .transport import RequestStats, request_served_signal
from .urls import direct_connect_url, webhook_connect_url
from .webhook import async_register_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]

# Set the first time any entry's async_setup_entry runs in this Python
# process. A config-entry *reload* (options change, subentry CRUD) tears
# down and rebuilds hass.data[DOMAIN][entry_id] but leaves this domain-level
# key untouched, so its presence reliably distinguishes "same process, just
# a reload" (safe to resume a grid bot's order placement unconditionally)
# from "fresh process after a restart" (conservative by default — see
# grid_bot.py's restart-behavior safety rule and async_setup_entry below).
_PROCESS_STARTED_KEY = f"{DOMAIN}_process_started"

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
        alert_coordinator: RevolutXAlertCoordinator,
        grid_bot_engines: dict[str, GridBotEngine],
    ) -> None:
        self.client = client
        self.direct_server = direct_server
        self.coordinator = coordinator
        self.stats = stats
        self.alert_coordinator = alert_coordinator
        self.grid_bot_engines = grid_bot_engines


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

    alert_coordinator = RevolutXAlertCoordinator(hass, entry, client)
    await alert_coordinator.async_config_entry_first_refresh()

    grid_bot_engines: dict[str, GridBotEngine] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_GRID_BOT:
            continue
        engine = GridBotEngine(hass, entry, subentry, client)
        await engine.async_load()
        grid_bot_engines[subentry.subentry_id] = engine

    # See _PROCESS_STARTED_KEY's own comment: this distinguishes "same
    # process, just a reload" from "fresh process after a restart" for the
    # grid-bot resume decision below.
    is_same_process_reload = hass.data.get(_PROCESS_STARTED_KEY, False)
    hass.data[_PROCESS_STARTED_KEY] = True

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = RuntimeData(
        client, direct_server, coordinator, stats, alert_coordinator, grid_bot_engines
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    for subentry_id, engine in grid_bot_engines.items():
        if not engine.state.running or engine.state.killed:
            continue
        # Reconcile fills/state immediately regardless (resting orders live
        # on Revolut X's own matching engine, not in this process, so this
        # is safe and keeps sensors accurate) — but only resume placing new
        # orders if this is a same-process reload (nothing dangerous
        # happened) or the bot explicitly opted into auto_resume. See
        # grid_bot.py's module docstring for the full reasoning.
        await engine.async_reconcile_only()
        auto_resume = bool(entry.subentries[subentry_id].data.get(CONF_AUTO_RESUME, DEFAULT_AUTO_RESUME))
        if is_same_process_reload or (trading_enabled and auto_resume):
            await engine.async_start()
        else:
            await engine.async_defer_resume()

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

    # Only cancel live grid-bot orders if trading has genuinely just been
    # turned off for this entry. entry.options already reflects any
    # just-applied change here — HA's async_update_entry sets it
    # synchronously before scheduling the update listener that leads to
    # this reload — so an options-only reload for something unrelated (e.g.
    # direct_server_port) leaves resting orders completely undisturbed;
    # async_setup_entry picks the same engine object's persisted state back
    # up next.
    trading_now_enabled = entry.options.get(CONF_TRADING_ENABLED, DEFAULT_TRADING_ENABLED)
    for engine in runtime.grid_bot_engines.values():
        if trading_now_enabled:
            engine.async_pause_for_reload()
        else:
            await engine.async_stop(cancel_orders=True)

    async_unregister_webhook(hass, entry.data[CONF_WEBHOOK_ID])
    await runtime.direct_server.async_stop()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed (auth mode, port, ...) — reload the entry to apply them."""
    await hass.config_entries.async_reload(entry.entry_id)
