"""Sensor entities: per-currency balances, active-order count, and the
push-updated MCP request-count/last-served-timestamp pair."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CATEGORY,
    CATEGORY_ACCOUNT,
    CATEGORY_HEALTH,
    CATEGORY_ORDER,
    CATEGORY_STRATEGY,
    CONF_PAIR,
    DOMAIN,
    SUBENTRY_TYPE_GRID_BOT,
)
from .coordinator import RevolutXDataUpdateCoordinator
from .device import device_info
from .grid_bot import GridBotEngine
from .transport import RequestStats


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: RevolutXDataUpdateCoordinator = runtime.coordinator

    known_currencies: set[str] = set()

    @callback
    def _add_new_currencies() -> None:
        new = set(coordinator.data.balances) - known_currencies
        if not new:
            return
        known_currencies.update(new)
        async_add_entities(
            RevolutXBalanceSensor(coordinator, entry, currency) for currency in new
        )

    _add_new_currencies()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_currencies))

    async_add_entities(
        [
            RevolutXActiveOrdersCountSensor(coordinator, entry),
            RevolutXRequestCountSensor(entry, runtime.stats),
            RevolutXLastServedSensor(entry, runtime.stats),
        ]
    )

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_GRID_BOT:
            continue
        engine = runtime.grid_bot_engines[subentry.subentry_id]
        async_add_entities(
            [
                RevolutXGridBotPnlSensor(engine, entry, subentry),
                RevolutXGridBotStatusSensor(engine, entry, subentry),
            ],
            config_subentry_id=subentry.subentry_id,
        )


class RevolutXBalanceSensor(CoordinatorEntity[RevolutXDataUpdateCoordinator], SensorEntity):
    """Spendable ("available") balance for one currency; reserved/total/staked
    as attributes. No MONETARY device_class — that HA device class requires an
    ISO 4217 currency, which excludes BTC/ETH; the currency code itself is used
    as the unit instead, the established pattern for crypto balance sensors.

    Entities are added as new currencies are first seen and never torn down if
    a currency later disappears from a poll response — they go `unavailable`
    instead, the correct HA idiom for "data source stopped reporting this" that
    avoids churning the entity registry / breaking History continuity.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "balance"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: RevolutXDataUpdateCoordinator, entry: ConfigEntry, currency: str
    ) -> None:
        super().__init__(coordinator)
        self._currency = currency
        self._attr_unique_id = f"{entry.entry_id}_balance_{currency.lower()}"
        self._attr_translation_placeholders = {"currency": currency}
        self._attr_native_unit_of_measurement = currency
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        return super().available and self._currency in self.coordinator.data.balances

    @property
    def native_value(self) -> Decimal | None:
        balance = self.coordinator.data.balances.get(self._currency)
        if not balance:
            return None
        try:
            return Decimal(balance["available"])
        except (InvalidOperation, KeyError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        balance = self.coordinator.data.balances.get(self._currency, {})
        return {
            "reserved": balance.get("reserved"),
            "total": balance.get("total"),
            "staked": balance.get("staked"),
            ATTR_CATEGORY: CATEGORY_ACCOUNT,
        }


class RevolutXActiveOrdersCountSensor(
    CoordinatorEntity[RevolutXDataUpdateCoordinator], SensorEntity
):
    """Count of open orders; the raw order list is available as an attribute.
    A very large open-order list could get truncated in Recorder history
    (HA's default attribute-size cutoff) while still showing correctly in the
    live UI — acceptable for a first pass, not a functional bug.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "active_orders_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RevolutXDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_active_orders_count"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.active_orders)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"orders": self.coordinator.data.active_orders, ATTR_CATEGORY: CATEGORY_ORDER}


class _RequestStatsSensor(SensorEntity):
    """Base for the push-updated (not coordinator-polled) request-tracking
    sensors — driven by RequestStats.record(), called from transport.py on
    every successfully-authenticated, well-formed MCP request.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, stats: RequestStats) -> None:
        self._stats = stats
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._stats.signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_CATEGORY: CATEGORY_HEALTH}


class RevolutXRequestCountSensor(_RequestStatsSensor):
    _attr_translation_key = "requests_served"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, entry: ConfigEntry, stats: RequestStats) -> None:
        super().__init__(entry, stats)
        self._attr_unique_id = f"{entry.entry_id}_requests_served"

    @property
    def native_value(self) -> int:
        return self._stats.count


class RevolutXLastServedSensor(_RequestStatsSensor):
    _attr_translation_key = "last_request_served"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: ConfigEntry, stats: RequestStats) -> None:
        super().__init__(entry, stats)
        self._attr_unique_id = f"{entry.entry_id}_last_request_served"

    @property
    def native_value(self):
        return self._stats.last_served


class _GridBotEntity:
    """Shared push-update wiring for grid-bot sensors — the engine notifies
    listeners itself after each tick (see grid_bot.py), there's no
    coordinator here since ticks are engine-owned, not shared."""

    def __init__(self, engine: GridBotEngine) -> None:
        self._engine = engine

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._engine.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class RevolutXGridBotPnlSensor(_GridBotEntity, SensorEntity):
    """Realized P&L for one live grid bot — see grid_bot.py for how
    position_base/committed_quote/realized_pnl are computed and the safety
    caps (investment ceiling, kill switch) that bound them."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL
    _attr_should_poll = False

    def __init__(self, engine: GridBotEngine, entry: ConfigEntry, subentry) -> None:
        super().__init__(engine)
        self._attr_name = f"{subentry.title} P&L"
        self._attr_unique_id = f"{entry.entry_id}_grid_bot_{subentry.subentry_id}_pnl"
        self._attr_device_info = device_info(entry)
        pair = str(subentry.data.get(CONF_PAIR, ""))
        self._attr_native_unit_of_measurement = pair.split("-")[-1] if "-" in pair else None

    @property
    def native_value(self) -> Decimal:
        return Decimal(self._engine.state.realized_pnl)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "position_base": self._engine.state.position_base,
            "committed_quote": self._engine.state.committed_quote,
            ATTR_CATEGORY: CATEGORY_STRATEGY,
        }


class RevolutXGridBotStatusSensor(_GridBotEntity, SensorEntity):
    """Status + grid/trade-log detail for one live grid bot. State changes
    land in HA's Logbook/History automatically — this is "the log," no
    separate log entity needed, the same mechanism
    RevolutXAlertRuleTriggeredSensor (binary_sensor.py) already relies on.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, engine: GridBotEngine, entry: ConfigEntry, subentry) -> None:
        super().__init__(engine)
        self._attr_name = f"{subentry.title} status"
        self._attr_unique_id = f"{entry.entry_id}_grid_bot_{subentry.subentry_id}_status"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str:
        if self._engine.state.killed:
            return "killed"
        return "running" if self._engine.is_running else "stopped"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "grid_levels": self._engine.state.grid_levels,
            "trade_log": self._engine.state.trade_log[-20:],
            "last_tick": self._engine.state.last_tick,
            "consecutive_errors": self._engine.state.consecutive_errors,
            "last_error": self._engine.state.last_error,
            ATTR_CATEGORY: CATEGORY_STRATEGY,
        }
