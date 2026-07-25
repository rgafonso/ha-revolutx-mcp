"""DataUpdateCoordinator polling Revolut X account data (balances + active orders)
on a user-configurable interval. Kept generic — a later price-alert monitor (see
ROADMAP.md) could extend this same coordinator's poll cycle with ticker/candle
fetches instead of polling independently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_MINUTES, DOMAIN
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class RevolutXData:
    """Snapshot of account data polled from Revolut X."""

    balances: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_orders: list[dict[str, Any]] = field(default_factory=list)


class RevolutXDataUpdateCoordinator(DataUpdateCoordinator[RevolutXData]):
    """Polls balances + active orders on a user-configurable interval."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: RevolutXClient) -> None:
        minutes = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_MINUTES)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=minutes),
        )
        self._client = client

    async def _async_update_data(self) -> RevolutXData:
        try:
            balances_raw = await self._client.get_balances()
            orders_raw = await self._client.get_active_orders()
        except RevolutXAuthError as err:
            raise ConfigEntryAuthFailed("Revolut X rejected the API key/signature") from err
        except RevolutXAPIError as err:
            raise UpdateFailed(str(err)) from err

        return RevolutXData(
            balances={b["currency"]: b for b in (balances_raw or [])},
            active_orders=(orders_raw or {}).get("data", []),
        )
