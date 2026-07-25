"""Binary sensors: rough "is this working" signals, plus trading_enabled
mirrored as an entity. See each class's docstring for what it does and does
not detect — the request-count/last-served sensors in sensor.py are the
actually useful "did my MCP server silently stop responding" signal, not
these.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TRADING_ENABLED, DEFAULT_TRADING_ENABLED, DOMAIN
from .device import device_info
from .direct_server import DirectServer


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RevolutXWebhookRegisteredSensor(entry),
            RevolutXDirectServerRunningSensor(entry, runtime.direct_server),
            RevolutXTradingEnabledSensor(entry),
        ]
    )


class RevolutXWebhookRegisteredSensor(BinarySensorEntity):
    """Whether the HA webhook is registered for this entry — NOT a network
    reachability check. HA's webhook component exposes no query API to detect
    that, and registration only fails by aborting setup entirely, so this
    reads "on" for the entire time this config entry is loaded.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "webhook_registered"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_is_on = True

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_webhook_registered"
        self._attr_device_info = device_info(entry)


class RevolutXDirectServerRunningSensor(BinarySensorEntity):
    """Whether the standalone direct-port server is bound and listening (off
    if the user disabled it via Options — that's not a failure state)."""

    _attr_has_entity_name = True
    _attr_translation_key = "direct_server_running"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, direct_server: DirectServer) -> None:
        self._direct_server = direct_server
        self._attr_unique_id = f"{entry.entry_id}_direct_server_running"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        return self._direct_server.is_running


class RevolutXTradingEnabledSensor(BinarySensorEntity):
    """Mirrors the trading_enabled options-flow toggle so it's visible on a
    dashboard instead of only in Settings > Options. Any options change
    already triggers a full entry reload (see __init__._async_update_listener),
    which recreates this entity with the fresh value — no separate update
    listener needed here.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "trading_enabled"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_trading_enabled"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        return self._entry.options.get(CONF_TRADING_ENABLED, DEFAULT_TRADING_ENABLED)
