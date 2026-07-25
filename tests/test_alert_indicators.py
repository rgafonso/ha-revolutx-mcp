"""Unit tests for price-alert indicator math and condition evaluation
(custom_components/revolutx_mcp/alert_indicators.py).

Pure functions, no Home Assistant instance needed — same style as
test_backtest.py.

Run from the repo root: `python -m unittest discover -s tests -t .`
"""
from __future__ import annotations

from decimal import Decimal
import unittest

from custom_components.revolutx_mcp import alert_indicators as ind
from custom_components.revolutx_mcp.const import (
    BAND_LOWER,
    BAND_UPPER,
    DIRECTION_ABOVE,
    DIRECTION_BEARISH,
    DIRECTION_BELOW,
    DIRECTION_BULLISH,
    DIRECTION_FALL,
    DIRECTION_RISE,
)


def _d(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


class ComputeRsiTests(unittest.TestCase):
    def test_not_enough_closes_returns_none(self) -> None:
        self.assertIsNone(ind.compute_rsi(_d("1", "2", "3"), period=5))

    def test_strictly_rising_closes_give_rsi_100(self) -> None:
        closes = _d(*[str(100 + i) for i in range(10)])
        self.assertEqual(ind.compute_rsi(closes, period=5), Decimal(100))

    def test_strictly_falling_closes_give_rsi_0(self) -> None:
        closes = _d(*[str(100 - i) for i in range(10)])
        self.assertEqual(ind.compute_rsi(closes, period=5), Decimal(0))


class EvaluatePriceTests(unittest.TestCase):
    def test_above_direction_met(self) -> None:
        met, detail = ind.evaluate_price(Decimal("101"), DIRECTION_ABOVE, Decimal("100"))
        self.assertTrue(met)
        self.assertIn("101", detail)

    def test_above_direction_not_met(self) -> None:
        met, _ = ind.evaluate_price(Decimal("99"), DIRECTION_ABOVE, Decimal("100"))
        self.assertFalse(met)

    def test_below_direction_met(self) -> None:
        met, _ = ind.evaluate_price(Decimal("99"), DIRECTION_BELOW, Decimal("100"))
        self.assertTrue(met)

    def test_below_direction_not_met(self) -> None:
        met, _ = ind.evaluate_price(Decimal("101"), DIRECTION_BELOW, Decimal("100"))
        self.assertFalse(met)


class EvaluatePriceChangeTests(unittest.TestCase):
    def test_not_enough_history_returns_none(self) -> None:
        result = ind.evaluate_price_change(
            Decimal("110"), _d("100", "101"), DIRECTION_RISE, Decimal("5"), lookback=24
        )
        self.assertIsNone(result)

    def test_rise_met(self) -> None:
        closes = _d(*(["100"] * 24))
        result = ind.evaluate_price_change(Decimal("110"), closes, DIRECTION_RISE, Decimal("5"), lookback=24)
        self.assertIsNotNone(result)
        met, detail = result
        self.assertTrue(met)
        self.assertIn("10.00%", detail)

    def test_rise_not_met(self) -> None:
        closes = _d(*(["100"] * 24))
        met, _ = ind.evaluate_price_change(Decimal("102"), closes, DIRECTION_RISE, Decimal("5"), lookback=24)
        self.assertFalse(met)

    def test_fall_met(self) -> None:
        closes = _d(*(["100"] * 24))
        met, _ = ind.evaluate_price_change(Decimal("90"), closes, DIRECTION_FALL, Decimal("5"), lookback=24)
        self.assertTrue(met)


class EvaluateRsiTests(unittest.TestCase):
    def test_not_enough_history_returns_none(self) -> None:
        result = ind.evaluate_rsi(_d("1", "2"), DIRECTION_ABOVE, Decimal("70"), period=14)
        self.assertIsNone(result)

    def test_overbought_triggers_above_direction(self) -> None:
        closes = _d(*[str(100 + i) for i in range(20)])
        result = ind.evaluate_rsi(closes, DIRECTION_ABOVE, Decimal("70"), period=14)
        self.assertIsNotNone(result)
        met, detail = result
        self.assertTrue(met)
        self.assertIn("RSI(14)", detail)

    def test_oversold_does_not_trigger_above_direction(self) -> None:
        closes = _d(*[str(100 - i) for i in range(20)])
        met, _ = ind.evaluate_rsi(closes, DIRECTION_ABOVE, Decimal("70"), period=14)
        self.assertFalse(met)


class EmaCrossTests(unittest.TestCase):
    def test_not_enough_history_returns_none(self) -> None:
        self.assertIsNone(ind.evaluate_ema_cross(_d("1", "2"), DIRECTION_BULLISH, 9, 21))

    def test_rising_closes_are_bullish(self) -> None:
        closes = _d(*[str(100 + i) for i in range(30)])
        met, detail = ind.evaluate_ema_cross(closes, DIRECTION_BULLISH, 9, 21)
        self.assertTrue(met)
        self.assertIn("EMA(9)", detail)

    def test_rising_closes_are_not_bearish(self) -> None:
        closes = _d(*[str(100 + i) for i in range(30)])
        met, _ = ind.evaluate_ema_cross(closes, DIRECTION_BEARISH, 9, 21)
        self.assertFalse(met)

    def test_falling_closes_are_bearish(self) -> None:
        closes = _d(*[str(100 - i) for i in range(30)])
        met, _ = ind.evaluate_ema_cross(closes, DIRECTION_BEARISH, 9, 21)
        self.assertTrue(met)


class MacdTests(unittest.TestCase):
    def test_not_enough_history_returns_none(self) -> None:
        self.assertIsNone(ind.evaluate_macd(_d("1", "2", "3"), DIRECTION_BULLISH, 12, 26, 9))

    def test_uptrend_after_flat_is_bullish(self) -> None:
        closes = _d(*(["100"] * 40 + [str(100 + i) for i in range(1, 11)]))
        result = ind.evaluate_macd(closes, DIRECTION_BULLISH, 12, 26, 9)
        self.assertIsNotNone(result)
        met, detail = result
        self.assertTrue(met)
        self.assertIn("histogram", detail)

    def test_downtrend_after_flat_is_bearish(self) -> None:
        closes = _d(*(["100"] * 40 + [str(100 - i) for i in range(1, 11)]))
        met, _ = ind.evaluate_macd(closes, DIRECTION_BEARISH, 12, 26, 9)
        self.assertTrue(met)


class BollingerTests(unittest.TestCase):
    def test_not_enough_history_returns_none(self) -> None:
        self.assertIsNone(
            ind.evaluate_bollinger(Decimal("100"), _d("1", "2"), BAND_UPPER, 20, Decimal("2"))
        )

    def test_price_above_upper_band_triggers(self) -> None:
        closes = _d(*(["100", "102"] * 10))  # mean 101, stdev 1
        met, detail = ind.evaluate_bollinger(Decimal("110"), closes, BAND_UPPER, 20, Decimal("2"))
        self.assertTrue(met)
        self.assertIn("upper band", detail)

    def test_price_inside_bands_does_not_trigger(self) -> None:
        closes = _d(*(["100", "102"] * 10))
        met, _ = ind.evaluate_bollinger(Decimal("101"), closes, BAND_UPPER, 20, Decimal("2"))
        self.assertFalse(met)

    def test_price_below_lower_band_triggers(self) -> None:
        closes = _d(*(["100", "102"] * 10))
        met, _ = ind.evaluate_bollinger(Decimal("90"), closes, BAND_LOWER, 20, Decimal("2"))
        self.assertTrue(met)


class VolumeSpikeTests(unittest.TestCase):
    def test_not_enough_history_returns_none(self) -> None:
        self.assertIsNone(ind.evaluate_volume_spike(_d("1", "2"), Decimal("2"), period=20))

    def test_spike_triggers(self) -> None:
        volumes = _d(*(["10"] * 20 + ["30"]))
        met, detail = ind.evaluate_volume_spike(volumes, Decimal("2"), period=20)
        self.assertTrue(met)
        self.assertIn("3.00x", detail)

    def test_normal_volume_does_not_trigger(self) -> None:
        volumes = _d(*(["10"] * 20 + ["15"]))
        met, _ = ind.evaluate_volume_spike(volumes, Decimal("2"), period=20)
        self.assertFalse(met)

    def test_zero_baseline_returns_none(self) -> None:
        volumes = _d(*(["0"] * 20 + ["10"]))
        self.assertIsNone(ind.evaluate_volume_spike(volumes, Decimal("2"), period=20))


class SpreadTests(unittest.TestCase):
    def test_wide_spread_triggers_above(self) -> None:
        # bid 99, ask 101 -> spread 2/100 = 2%
        met, detail = ind.evaluate_spread(Decimal("99"), Decimal("101"), DIRECTION_ABOVE, Decimal("1"))
        self.assertTrue(met)
        self.assertIn("2.0000%", detail)

    def test_tight_spread_does_not_trigger_above(self) -> None:
        met, _ = ind.evaluate_spread(Decimal("99.99"), Decimal("100.01"), DIRECTION_ABOVE, Decimal("1"))
        self.assertFalse(met)

    def test_invalid_quotes_return_none(self) -> None:
        self.assertIsNone(ind.evaluate_spread(Decimal("0"), Decimal("100"), DIRECTION_ABOVE, Decimal("1")))


class ObiTests(unittest.TestCase):
    def test_buy_pressure_triggers_above(self) -> None:
        met, detail = ind.evaluate_obi(Decimal("80"), Decimal("20"), DIRECTION_ABOVE, Decimal("0.3"))
        self.assertTrue(met)  # OBI = 60/100 = 0.6
        self.assertIn("Buy pressure", detail)

    def test_balanced_book_does_not_trigger(self) -> None:
        met, _ = ind.evaluate_obi(Decimal("50"), Decimal("50"), DIRECTION_ABOVE, Decimal("0.3"))
        self.assertFalse(met)

    def test_sell_pressure_triggers_below(self) -> None:
        met, detail = ind.evaluate_obi(Decimal("20"), Decimal("80"), DIRECTION_BELOW, Decimal("-0.3"))
        self.assertTrue(met)
        self.assertIn("Sell pressure", detail)

    def test_empty_book_returns_none(self) -> None:
        self.assertIsNone(ind.evaluate_obi(Decimal("0"), Decimal("0"), DIRECTION_ABOVE, Decimal("0.3")))


class AtrBreakoutTests(unittest.TestCase):
    def _flat_series(self, n: int) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
        highs = _d(*(["101"] * n))
        lows = _d(*(["99"] * n))
        closes = _d(*(["100"] * n))
        return highs, lows, closes

    def test_not_enough_history_returns_none(self) -> None:
        self.assertIsNone(
            ind.evaluate_atr_breakout(Decimal("100"), _d("1"), _d("1"), _d("1"), Decimal("1.5"), 14)
        )

    def test_large_move_triggers(self) -> None:
        highs, lows, closes = self._flat_series(20)  # ATR = 2
        met, detail = ind.evaluate_atr_breakout(Decimal("110"), closes, highs, lows, Decimal("1.5"), 14)
        self.assertTrue(met)  # move 10 >= 2*1.5=3
        self.assertIn("ATR(14)", detail)

    def test_small_move_does_not_trigger(self) -> None:
        highs, lows, closes = self._flat_series(20)
        met, _ = ind.evaluate_atr_breakout(Decimal("101"), closes, highs, lows, Decimal("1.5"), 14)
        self.assertFalse(met)  # move 1 < 3

    def test_fires_in_either_direction(self) -> None:
        highs, lows, closes = self._flat_series(20)
        met, _ = ind.evaluate_atr_breakout(Decimal("90"), closes, highs, lows, Decimal("1.5"), 14)
        self.assertTrue(met)


if __name__ == "__main__":
    unittest.main()
