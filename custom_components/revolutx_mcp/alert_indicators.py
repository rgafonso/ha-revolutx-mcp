"""Pure indicator math + condition evaluation for price-alert rules.

Full parity with the upstream revx CLI's 10 `monitor` indicator types (see
ROADMAP.md's now-removed "remaining indicator types" note). Math confirmed
against the upstream CLI's `cli/src/shared/indicators/core.ts` during this
session's research:

- RSI/ATR use Wilder smoothing: seed the average over the first `period`
  values, then smooth `(avg*(period-1)+new)/period` per subsequent value.
- EMA uses the standard `multiplier = 2/(period+1)`, seeded with a simple
  average of the first `period` closes.
- MACD's signal line is just an EMA of the MACD line series — reuses the
  same `compute_ema`/`compute_ema_series` helpers, not separate math.
- Bollinger uses Python's built-in `Decimal.sqrt()` for the population
  stdev, unlike upstream's hand-rolled Newton's-method sqrt (only needed
  there because JS has no arbitrary-precision decimal sqrt built in).

`closes`/`highs`/`lows`/`volumes` are always ascending-by-time (oldest
first), matching `backtest.Candle`'s own sort order — these functions take
plain `Decimal` lists rather than `Candle` objects so they stay
independently testable.
"""
from __future__ import annotations

from decimal import Decimal

from .const import BAND_UPPER, DIRECTION_ABOVE, DIRECTION_BULLISH, DIRECTION_RISE


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


def compute_ema(closes: list[Decimal], period: int) -> Decimal | None:
    """Standard EMA, seeded with a simple average of the first `period` values."""
    if len(closes) < period:
        return None
    multiplier = Decimal(2) / (period + 1)
    ema = sum(closes[:period], Decimal(0)) / period
    for close in closes[period:]:
        ema = (close - ema) * multiplier + ema
    return ema


def compute_ema_series(closes: list[Decimal], period: int) -> list[Decimal]:
    """Full EMA series (one value per close once the seed window fills) — needed
    to compute MACD's signal line, which is itself an EMA of the MACD line."""
    if len(closes) < period:
        return []
    multiplier = Decimal(2) / (period + 1)
    ema = sum(closes[:period], Decimal(0)) / period
    series = [ema]
    for close in closes[period:]:
        ema = (close - ema) * multiplier + ema
        series.append(ema)
    return series


def evaluate_ema_cross(
    closes: list[Decimal], direction: str, fast_period: int, slow_period: int
) -> tuple[bool, str] | None:
    fast = compute_ema(closes, fast_period)
    slow = compute_ema(closes, slow_period)
    if fast is None or slow is None:
        return None
    met = fast > slow if direction == DIRECTION_BULLISH else fast < slow
    op = ">" if direction == DIRECTION_BULLISH else "<"
    return met, f"EMA({fast_period})={fast:.4f} {op} EMA({slow_period})={slow:.4f}"


def evaluate_macd(
    closes: list[Decimal], direction: str, fast_period: int, slow_period: int, signal_period: int
) -> tuple[bool, str] | None:
    fast_series = compute_ema_series(closes, fast_period)
    slow_series = compute_ema_series(closes, slow_period)
    if not fast_series or not slow_series:
        return None
    # fast_series starts earlier (shorter seed window) than slow_series — align
    # both to the slow series' start before diffing.
    offset = len(fast_series) - len(slow_series)
    if offset < 0:
        return None
    macd_series = [f - s for f, s in zip(fast_series[offset:], slow_series)]
    signal = compute_ema(macd_series, signal_period)
    if signal is None:
        return None
    macd_value = macd_series[-1]
    histogram = macd_value - signal
    met = macd_value > signal if direction == DIRECTION_BULLISH else macd_value < signal
    return met, f"MACD={macd_value:.4f} signal={signal:.4f} histogram={histogram:.4f}"


def evaluate_bollinger(
    price: Decimal, closes: list[Decimal], band: str, period: int, std_mult: Decimal
) -> tuple[bool, str] | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window, Decimal(0)) / period
    variance = sum(((c - mean) ** 2 for c in window), Decimal(0)) / period
    stdev = variance.sqrt()
    if band == BAND_UPPER:
        upper = mean + std_mult * stdev
        return price >= upper, f"Price {price} vs upper band {upper:.4f} (mid {mean:.4f})"
    lower = mean - std_mult * stdev
    return price <= lower, f"Price {price} vs lower band {lower:.4f} (mid {mean:.4f})"


def evaluate_volume_spike(
    volumes: list[Decimal], multiplier: Decimal, period: int
) -> tuple[bool, str] | None:
    """Average volume is over the `period` candles *preceding* the current
    one (the current candle's own volume is excluded from its baseline),
    matching the upstream CLI's semantics."""
    if len(volumes) < period + 1:
        return None
    current = volumes[-1]
    baseline = volumes[-(period + 1) : -1]
    avg = sum(baseline, Decimal(0)) / period
    if avg == 0:
        return None
    ratio = current / avg
    met = ratio >= multiplier
    return met, f"Volume {current} is {ratio:.2f}x the {period}-candle average {avg:.2f} (threshold {multiplier}x)"


def evaluate_spread(
    bid: Decimal, ask: Decimal, direction: str, threshold_pct: Decimal
) -> tuple[bool, str] | None:
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    if mid == 0:
        return None
    spread_pct = (ask - bid) / mid * 100
    met = spread_pct >= threshold_pct if direction == DIRECTION_ABOVE else spread_pct <= threshold_pct
    op = ">=" if direction == DIRECTION_ABOVE else "<="
    return met, f"Spread {spread_pct:.4f}% {op} threshold {threshold_pct}%"


def evaluate_obi(
    bid_volume: Decimal, ask_volume: Decimal, direction: str, threshold: Decimal
) -> tuple[bool, str] | None:
    """Order-book imbalance: (bidVol-askVol)/(bidVol+askVol), range -1..1."""
    total = bid_volume + ask_volume
    if total == 0:
        return None
    obi = (bid_volume - ask_volume) / total
    met = obi >= threshold if direction == DIRECTION_ABOVE else obi <= threshold
    label = "Buy pressure" if obi > 0 else "Sell pressure"
    return met, f"{label}: OBI {obi:.4f} (threshold {threshold})"


def compute_atr(
    highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], period: int
) -> Decimal | None:
    if len(closes) < period + 1 or len(highs) != len(closes) or len(lows) != len(closes):
        return None
    true_ranges = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    avg_tr = sum(true_ranges[:period], Decimal(0)) / period
    for tr in true_ranges[period:]:
        avg_tr = (avg_tr * (period - 1) + tr) / period
    return avg_tr


def evaluate_atr_breakout(
    price: Decimal, closes: list[Decimal], highs: list[Decimal], lows: list[Decimal],
    multiplier: Decimal, period: int,
) -> tuple[bool, str] | None:
    """Fires on a large move in *either* direction, not a directional
    breakout — matches the upstream CLI's `atr-breakout` (no --direction
    flag there either)."""
    atr = compute_atr(highs, lows, closes, period)
    if atr is None:
        return None
    move = abs(price - closes[-1])
    threshold = atr * multiplier
    met = move >= threshold
    return met, f"Move {move:.4f} vs ATR({period})x{multiplier}={threshold:.4f}"
