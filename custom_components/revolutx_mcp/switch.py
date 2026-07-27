"""Switch platform: start/stop for live grid-trading bots. See grid_bot.py
for the engine and its safety design.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CATEGORY,
    CATEGORY_HEALTH,
    CATEGORY_STRATEGY,
    CONF_TRADING_ENABLED,
    DEFAULT_TRADING_ENABLED,
    DOMAIN,
    SUBENTRY_TYPE_GRID_BOT,
)
from .device import device_info
from .grid_bot import GridBotEngine


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([RevolutXTradingEnabledSwitch(hass, entry)])

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_GRID_BOT:
            continue
        engine = runtime.grid_bot_engines[subentry.subentry_id]
        async_add_entities(
            [RevolutXGridBotSwitch(engine, entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class RevolutXTradingEnabledSwitch(SwitchEntity):
    """Turns the `trading_enabled` options-flow value on/off directly from a
    dashboard, instead of only via Settings > Options. Writing through
    `hass.config_entries.async_update_entry` fires the same update listener
    (`__init__._async_update_listener`) a change made through the Options UI
    already would, which fully reloads this config entry — including
    `async_unload_entry`'s existing handling of live grid bots (their
    resting orders get cancelled if trading is being turned off, or just
    paused-and-resumed if it's staying on) — so no separate control logic
    is needed here, only writing the option.

    Turning this off while a grid bot is running will cancel its live
    resting orders, same as flipping it off in Options today.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "trading_enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_trading_enabled"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        return self._entry.options.get(CONF_TRADING_ENABLED, DEFAULT_TRADING_ENABLED)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._async_set(False)

    @callback
    def _async_set(self, value: bool) -> None:
        self._hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_TRADING_ENABLED: value}
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_CATEGORY: CATEGORY_HEALTH}


class RevolutXGridBotSwitch(SwitchEntity):
    """Start/stop for one grid bot.

    Deliberately NOT a RestoreEntity: the engine's persisted Store
    `state.running` (see grid_bot.py) is the single authoritative record of
    run-state. Layering HA's own entity-state restore on top would create a
    second, independently-persisted copy that could disagree with the Store
    after a crash mid-write — this entity just reflects and drives the
    engine live, via `is_on`/`async_turn_on`/`async_turn_off`, so there's
    exactly one source of truth.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, engine: GridBotEngine, entry: ConfigEntry, subentry) -> None:
        self._engine = engine
        self._attr_name = subentry.title
        self._attr_unique_id = f"{entry.entry_id}_grid_bot_{subentry.subentry_id}_switch"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._engine.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._engine.is_running

    @property
    def available(self) -> bool:
        # Two-factor arming: the real enforcement lives inside the engine
        # (checked every tick, and again in async_start), this is just a UX
        # signal so the toggle is visibly disabled rather than silently
        # doing nothing when trading is off in this entry's Options.
        return self._engine.trading_allowed

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._engine.async_start()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._engine.async_stop(cancel_orders=True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "killed": self._engine.state.killed,
            "consecutive_errors": self._engine.state.consecutive_errors,
            "last_error": self._engine.state.last_error,
            ATTR_CATEGORY: CATEGORY_STRATEGY,
        }
