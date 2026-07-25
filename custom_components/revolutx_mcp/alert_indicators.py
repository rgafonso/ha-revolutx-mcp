"""Pure indicator math + condition evaluation for price-alert rules.

Scope for this pass (see ROADMAP.md): price threshold, price-change %, and
RSI only — the 3 most commonly wanted of the upstream revx CLI's 10 monitor
types (MACD/Bollinger/volume-spike/spread/OBI/ATR/EMA-cross deferred).

RSI uses the same Wilder-smoothing shape confirmed against the upstream CLI's
`cli/src/shared/indicators/core.ts` during this session's research: seed the
average gain/loss over the first `period` deltas, then smooth
`(avg*(period-1)+new)/period` per subsequent delta.

`closes` is always ascending-by-time (oldest first), matching
`backtest.Candle`'s own sort order — these functions take plain `Decimal`
lists rather than `Candle` objects so they stay independently testable.
"""
from __future__ import annotations

from decimal import Decimal

from .const import DIRECTION_ABOVE, DIRECTION_RISE


def compute_rsi(closes: list[Decimal], period: int) -> Decimal | None:
    """Wilder-smoothed RSI, or None if there aren't enough closes yet."""
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else Decimal(0) for d in deltas]
    losses = [-d if d < 0 else Decimal(0) for d in deltas]

    avg_gain = sum(gains[:period], Decimal(0)) / period
    avg_loss = sum(losses[:period], Decimal(0)) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return Decimal(100)
    rs = avg_gain / avg_loss
    return Decimal(100) - (Decimal(100) / (1 + rs))


def evaluate_price(price: Decimal, direction: str, threshold: Decimal) -> tuple[bool, str]:
    met = price >= threshold if direction == DIRECTION_ABOVE else price <= threshold
    op = ">=" if direction == DIRECTION_ABOVE else "<="
    return met, f"Price {price} {op} threshold {threshold}"


def evaluate_price_change(
    current_price: Decimal, closes: list[Decimal], direction: str, threshold_pct: Decimal, lookback: int
) -> tuple[bool, str] | None:
    """None if there isn't enough candle history yet for the requested lookback."""
    if len(closes) < lookback or closes[-lookback] == 0:
        return None
    past = closes[-lookback]
    pct_change = (current_price - past) / past * 100
    met = pct_change >= threshold_pct if direction == DIRECTION_RISE else pct_change <= -threshold_pct
    return met, f"Price changed {pct_change:.2f}% over the last {lookback} candles (threshold {threshold_pct}%)"


def evaluate_rsi(
    closes: list[Decimal], direction: str, threshold: Decimal, period: int
) -> tuple[bool, str] | None:
    """None if there isn't enough candle history yet to seed the RSI window."""
    rsi = compute_rsi(closes, period)
    if rsi is None:
        return None
    met = rsi >= threshold if direction == DIRECTION_ABOVE else rsi <= threshold
    op = ">=" if direction == DIRECTION_ABOVE else "<="
    return met, f"RSI({period}) is {rsi:.2f} {op} threshold {threshold}"
