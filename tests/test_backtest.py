"""Unit tests for the grid-backtest engine (custom_components/revolutx_mcp/backtest.py).

This is the one piece of the 0.4.0 release with no live system to sanity-check
against (unlike the write-tool REST calls or the static KB content), so it's the
only part of this integration with automated tests — see that module's README
section for why the rest is still verified via py_compile + a manual live check.

Run from the repo root: `python -m unittest discover -s tests -t .`
Requires `homeassistant` (and its own transitive deps) installed, same as the
existing `python -c "import custom_components.revolutx_mcp"` smoke test — this
package's __init__.py imports Home Assistant modules on import.
"""
from __future__ import annotations

import time
import unittest
from decimal import Decimal
from unittest import mock

from custom_components.revolutx_mcp import backtest


def _candle(start: int, open_: str, high: str, low: str, close: str) -> backtest.Candle:
    return backtest.Candle(
        start=start, open=Decimal(open_), high=Decimal(high), low=Decimal(low), close=Decimal(close)
    )


class CreateGridTests(unittest.TestCase):
    def test_level_count_and_spacing(self) -> None:
        levels = backtest.create_grid(Decimal(100), 2, Decimal("0.1"), quote_dp=2)
        self.assertEqual(len(levels), 2)
        self.assertEqual(levels[0].price, Decimal("90.00"))
        self.assertEqual(levels[1].price, Decimal("110.00"))

    def test_initial_buy_count(self) -> None:
        levels = backtest.create_grid(Decimal(100), 2, Decimal("0.1"), quote_dp=2)
        self.assertEqual(levels[0].buy_count, 1)  # 90 < 100
        self.assertEqual(levels[1].buy_count, 0)  # 110 >= 100


class RunBacktestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_step = Decimal("0.00001")
        self.quote_step = Decimal("0.01")

    def test_one_buy_then_sell_round_trip(self) -> None:
        candles = [
            _candle(1, "100", "100", "85", "95"),  # bearish -> buy pass fires at low<=90
            _candle(2, "95", "115", "95", "110"),  # bullish -> sell pass fires at high>=110
        ]
        result = backtest.run_backtest(
            candles,
            grid_levels_total=2,
            range_pct=Decimal("0.1"),
            investment=Decimal(1000),
            split_investment=False,
            trailing_up=False,
            stop_loss_price=Decimal(0),
            base_step=self.base_step,
            quote_step=self.quote_step,
        )
        self.assertEqual(result["total_buys"], 1)
        self.assertEqual(result["total_sells"], 1)
        self.assertEqual(result["total_trades"], 2)
        self.assertEqual(result["realized_pnl"], Decimal("222.22"))
        self.assertEqual(result["final_base"], Decimal(0))
        self.assertEqual(result["final_quote"], Decimal("1222.22"))
        self.assertFalse(result["stop_loss_triggered"])

    def test_stop_loss_ends_simulation_immediately(self) -> None:
        candles = [
            _candle(1, "100", "100", "75", "80"),  # low breaches stop_loss_price=80 immediately
            _candle(2, "80", "80", "85", "85"),  # would buy (low<=90) if this were reached
        ]
        result = backtest.run_backtest(
            candles,
            grid_levels_total=2,
            range_pct=Decimal("0.1"),
            investment=Decimal(1000),
            split_investment=False,
            trailing_up=False,
            stop_loss_price=Decimal(80),
            base_step=self.base_step,
            quote_step=self.quote_step,
        )
        self.assertTrue(result["stop_loss_triggered"])
        self.assertEqual(result["total_buys"], 0)
        self.assertEqual(result["total_trades"], 0)


class ResolutionMinutesTests(unittest.TestCase):
    def test_exhaustive_over_documented_enum(self) -> None:
        self.assertEqual(
            set(backtest.RESOLUTION_MINUTES),
            {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "2d", "4d", "1w", "2w", "4w"},
        )
        self.assertEqual(backtest.RESOLUTION_MINUTES["1h"], 60)
        self.assertEqual(backtest.RESOLUTION_MINUTES["1d"], 1440)
        self.assertEqual(backtest.RESOLUTION_MINUTES["4w"], 40320)


class FetchCandlesWindowingTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_window_is_capped_and_paginated(self) -> None:
        fixed_now_s = 1_700_000_000.0
        now_ms = int(fixed_now_s * 1000)
        interval_minutes = 60
        interval_ms = interval_minutes * 60_000

        with mock.patch.object(backtest, "MAX_CANDLES", 300), mock.patch.object(
            backtest.time, "time", return_value=fixed_now_s
        ):
            client = mock.Mock()
            client.get_candles = mock.AsyncMock(return_value={"data": []})

            await backtest.fetch_candles(client, "BTC-USD", "1h", days=1000)

            self.assertEqual(client.get_candles.call_count, 3)
            expected_start = now_ms - 300 * interval_ms
            first_call_kwargs = client.get_candles.call_args_list[0].kwargs
            self.assertEqual(first_call_kwargs["since"], expected_start)
            self.assertEqual(first_call_kwargs["interval"], interval_minutes)
            last_call_kwargs = client.get_candles.call_args_list[-1].kwargs
            self.assertEqual(last_call_kwargs["until"], now_ms)


class GridOptimizeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_oversized_combo_count(self) -> None:
        args = {
            "symbol": "BTC-USD",
            "grid_levels_options": ",".join(str(n) for n in range(1, 22)),  # 21 values
            "range_pct_options": ",".join(str(n) for n in range(1, 11)),  # 10 values -> 210 combos
        }
        with self.assertRaises(ValueError):
            await backtest.grid_optimize_tool(client=None, args=args)


if __name__ == "__main__":
    unittest.main()
