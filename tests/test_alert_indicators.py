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
    DIRECTION_ABOVE,
    DIRECTION_BELOW,
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


if __name__ == "__main__":
    unittest.main()
