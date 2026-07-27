"""Binary sensors: rough "is this working" signals. See each class's
docstring for what it does and does not detect — the request-count/
last-served sensors in sensor.py are the actually useful "did my MCP server
silently stop responding" signal, not these. `trading_enabled` used to be
mirrored here read-only; it's now a controllable switch (see switch.py).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alert_coordinator import RevolutXAlertCoordinator
from .const import ATTR_CATEGORY, CATEGORY_HEALTH, CATEGORY_MONITOR, DOMAIN, SUBENTRY_TYPE_ALERT_RULE
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
        ]
    )

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_ALERT_RULE:
            continue
        async_add_entities(
            [RevolutXAlertRuleTriggeredSensor(runtime.alert_coordinator, entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class RevolutXWebhookRegisteredSensor(BinarySensorEntity):
    """Whether the HA webhook is registered for this entry — NOT a network
    reachability check. HA's webhook component exposes no query API to detect
    that, and registration only fails by aborting setup entirely, so this
    reads "on" for the entire time this config entry is loaded.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "webhook_registered"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_is_on = True

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_webhook_registered"
        self._attr_device_info = device_info(entry)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_CATEGORY: CATEGORY_HEALTH}


class RevolutXDirectServerRunningSensor(BinarySensorEntity):
    """Whether the standalone direct-port server is bound and listening (off
    if the user disabled it via Options — that's not a failure state)."""

    _attr_has_entity_name = True
    _attr_translation_key = "direct_server_running"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, direct_server: DirectServer) -> None:
        self._direct_server = direct_server
        self._attr_unique_id = f"{entry.entry_id}_direct_server_running"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        return self._direct_server.is_running

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_CATEGORY: CATEGORY_HEALTH}


class RevolutXAlertRuleTriggeredSensor(CoordinatorEntity[RevolutXAlertCoordinator], BinarySensorEntity):
    """Triggered/not for one price-alert rule (a subentry) — mirrors
    RevolutXAlertCoordinator's edge-triggered evaluation, so it shows up in
    HA's Logbook/History per ROADMAP.md's original "alert history" direction.
    Removed automatically by HA core when its subentry is deleted (tagged
    with config_subentry_id at creation, in this module's async_setup_entry).
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: RevolutXAlertCoordinator, entry: ConfigEntry, subentry) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry.subentry_id
        self._attr_name = subentry.title
        self._attr_unique_id = f"{entry.entry_id}_alert_{subentry.subentry_id}"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        state = self.coordinator.data.get(self._subentry_id) if self.coordinator.data else None
        return state.triggered if state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.coordinator.data.get(self._subentry_id) if self.coordinator.data else None
        if not state:
            return {ATTR_CATEGORY: CATEGORY_MONITOR}
        return {
            "detail": state.detail,
            "last_triggered": state.last_triggered,
            ATTR_CATEGORY: CATEGORY_MONITOR,
        }
