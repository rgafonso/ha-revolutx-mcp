"""Unit tests for RevolutXDataUpdateCoordinator's data shaping and error mapping
(custom_components/revolutx_mcp/coordinator.py).

No real Home Assistant instance is used — same constraint as test_backtest.py
(see that file's docstring). `_async_update_data()` is called directly, so a
MagicMock `hass` and a minimal fake `entry` (only `.entry_id`/`.options` are
read by DataUpdateCoordinator.__init__ before any real refresh happens) are
enough.

Run from the repo root: `python -m unittest discover -s tests -t .`
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.revolutx_mcp.coordinator import RevolutXDataUpdateCoordinator
from custom_components.revolutx_mcp.revolut_client import RevolutXAPIError, RevolutXAuthError


def _make_coordinator(client: MagicMock) -> RevolutXDataUpdateCoordinator:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = {}
    return RevolutXDataUpdateCoordinator(hass, entry, client)


class RevolutXDataUpdateCoordinatorTests(unittest.TestCase):
    def test_shapes_balances_and_orders(self) -> None:
        client = MagicMock()
        client.get_balances = AsyncMock(
            return_value=[
                {"currency": "BTC", "available": "1.25", "reserved": "0.10", "total": "1.35"},
                {"currency": "USD", "available": "500.00", "reserved": "0", "total": "500.00"},
            ]
        )
        client.get_active_orders = AsyncMock(
            return_value={"data": [{"id": "abc", "symbol": "BTC/USD"}], "metadata": {}}
        )
        coordinator = _make_coordinator(client)

        data = asyncio.run(coordinator._async_update_data())

        self.assertEqual(set(data.balances), {"BTC", "USD"})
        self.assertEqual(data.balances["BTC"]["available"], "1.25")
        self.assertEqual(len(data.active_orders), 1)
        self.assertEqual(data.active_orders[0]["id"], "abc")

    def test_empty_responses(self) -> None:
        client = MagicMock()
        client.get_balances = AsyncMock(return_value=[])
        client.get_active_orders = AsyncMock(return_value={"data": []})
        coordinator = _make_coordinator(client)

        data = asyncio.run(coordinator._async_update_data())

        self.assertEqual(data.balances, {})
        self.assertEqual(data.active_orders, [])

    def test_auth_error_maps_to_config_entry_auth_failed(self) -> None:
        client = MagicMock()
        client.get_balances = AsyncMock(side_effect=RevolutXAuthError("bad key"))
        client.get_active_orders = AsyncMock(return_value={"data": []})
        coordinator = _make_coordinator(client)

        with self.assertRaises(ConfigEntryAuthFailed):
            asyncio.run(coordinator._async_update_data())

    def test_api_error_maps_to_update_failed(self) -> None:
        client = MagicMock()
        client.get_balances = AsyncMock(return_value=[])
        client.get_active_orders = AsyncMock(side_effect=RevolutXAPIError(500, "boom"))
        coordinator = _make_coordinator(client)

        with self.assertRaises(UpdateFailed):
            asyncio.run(coordinator._async_update_data())


if __name__ == "__main__":
    unittest.main()
