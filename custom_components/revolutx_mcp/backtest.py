"""Historical grid-trading strategy simulation (`grid_backtest` / `grid_optimize`
MCP tools) — pure historical simulation against candle data already available via
`RevolutXClient.get_candles`. No live orders are ever placed; always enabled,
unlike the order-write tools in `revolut_client.py`.

Ported from the upstream `revolut-x-api` repo's `mcp/src/shared/backtest/engine.ts`
(same algorithm, translated to Python `decimal.Decimal` arithmetic) with one added
piece of plumbing: our REST client caps `get_candles` at ~100 candles per call,
unlike upstream's internally-paginated client, so `fetch_candles` below loops in
sub-windows to assemble a full series.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation, getcontext
from typing import Any

from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient

getcontext().prec = 28

RESOLUTION_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "2d": 2880,
    "4d": 5760,
    "1w": 10080,
    "2w": 20160,
    "4w": 40320,
}

MAX_CANDLES = 50_000
CANDLES_PER_CALL = 100
MAX_OPTIMIZE_COMBOS = 200
_MAX_SHIFT_ITERATIONS = 10_000

_DEFAULT_BASE_STEP = Decimal("0.00001")
_DEFAULT_QUOTE_STEP = Decimal("0.01")


@dataclass
class Candle:
    start: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal(0)


@dataclass
class GridLevel:
    price: Decimal
    buy_count: int
    positions: list[Decimal] = field(default_factory=list)


def _decimal_places(step: Decimal) -> int:
    exponent = step.normalize().as_tuple().exponent
    return max(-exponent, 0) if isinstance(exponent, int) else 0


def _round_down(value: Decimal, dp: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_DOWN)


def _round(value: Decimal, dp: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)


def _parse_candles(raw: list[dict[str, Any]]) -> list[Candle]:
    candles: list[Candle] = []
    for item in raw:
        try:
            candles.append(
                Candle(
                    start=int(item["start"]),
                    open=Decimal(str(item["open"])),
                    high=Decimal(str(item["high"])),
                    low=Decimal(str(item["low"])),
                    close=Decimal(str(item["close"])),
                    # Lenient: volume is only used by the volume-spike alert indicator,
                    # not by grid-backtest math, so a missing/invalid value shouldn't
                    # break candle parsing for callers that don't need it.
                    volume=Decimal(str(item.get("volume", "0")) or "0"),
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    candles.sort(key=lambda c: c.start)
    return candles


async def fetch_candles(client: RevolutXClient, symbol: str, resolution: str, days: int) -> list[Candle]:
    """Ascending-by-time candles covering `days` at `resolution`, capped at
    MAX_CANDLES (shrinking the window to the most recent MAX_CANDLES if the
    naive window would exceed it), assembled from <=100-candle sub-windows."""
    interval_minutes = RESOLUTION_MINUTES.get(resolution, 60)
    interval_ms = interval_minutes * 60_000
    now = int(time.time() * 1000)
    start = now - days * 24 * 60 * 60 * 1000

    expected = -(-(now - start) // interval_ms)  # ceil division
    if expected > MAX_CANDLES:
        start = now - MAX_CANDLES * interval_ms

    window_span_ms = CANDLES_PER_CALL * interval_ms
    seen_starts: set[int] = set()
    candles: list[Candle] = []
    window_start = start
    while window_start < now:
        window_end = min(window_start + window_span_ms, now)
        response = await client.get_candles(
            symbol, interval=interval_minutes, since=window_start, until=window_end
        )
        raw = response.get("data", []) if isinstance(response, dict) else []
        for candle in _parse_candles(raw):
            if candle.start not in seen_starts:
                seen_starts.add(candle.start)
                candles.append(candle)
        window_start = window_end

    candles.sort(key=lambda c: c.start)
    return candles


async def get_step_sizes(client: RevolutXClient, symbol: str) -> tuple[Decimal, Decimal]:
    """(base_step, quote_step) for `symbol`, from `client.get_pairs()`. Falls back
    to conservative defaults on any lookup failure — a backtest should never
    hard-fail just because pair metadata lookup had an issue."""
    try:
        pairs = await client.get_pairs()
        pair = pairs.get(symbol) if isinstance(pairs, dict) else None
        if pair:
            return Decimal(str(pair["base_step"])), Decimal(str(pair["quote_step"]))
    except (RevolutXAuthError, RevolutXAPIError, KeyError, TypeError, InvalidOperation):
        pass
    return _DEFAULT_BASE_STEP, _DEFAULT_QUOTE_STEP


def create_grid(start_price: Decimal, grid_levels_total: int, range_pct: Decimal, quote_dp: int) -> list[GridLevel]:
    lower = start_price * (1 - range_pct)
    upper = start_price * (1 + range_pct)
    ratio = (upper / lower) ** (Decimal(1) / (grid_levels_total - 1))
    levels = []
    for i in range(grid_levels_total):
        price = _round(lower * (ratio**i), quote_dp)
        buy_count = 1 if price < start_price else 0
        levels.append(GridLevel(price=price, buy_count=buy_count))
    return levels


def run_backtest(
    candles: list[Candle],
    grid_levels_total: int,
    range_pct: Decimal,
    investment: Decimal,
    split_investment: bool,
    trailing_up: bool,
    stop_loss_price: Decimal,
    base_step: Decimal,
    quote_step: Decimal,
) -> dict[str, Any]:
    base_dp = _decimal_places(base_step)
    quote_dp = _decimal_places(quote_step)

    start_price = candles[0].open
    levels = create_grid(start_price, grid_levels_total, range_pct, quote_dp)

    buy_level_count = sum(1 for lvl in levels if lvl.buy_count > 0)
    sell_level_indices = [i for i, lvl in enumerate(levels) if lvl.price > start_price] if split_investment else []
    total_capital_levels = (buy_level_count + len(sell_level_indices)) if split_investment else buy_level_count
    quote_per_level = _round_down(investment / max(total_capital_levels, 1), 2)

    quote_balance = investment
    peak_value = investment
    max_drawdown = Decimal(0)
    total_trades = total_buys = total_sells = 0
    realized_pnl = Decimal(0)
    trailing_up_shifts = 0
    stop_loss_triggered = False
    trade_log: list[str] = []

    if split_investment and sell_level_indices:
        base_per_level = _round_down(quote_per_level / start_price, base_dp)
        for idx in sell_level_indices:
            buy_level = levels[idx - 1]
            buy_level.positions.append(base_per_level)
        quote_balance -= quote_per_level * len(sell_level_indices)

    fixed_sl_price = stop_loss_price if stop_loss_price > 0 else None

    def _liquidate_all(price: Decimal, tag: str) -> None:
        nonlocal quote_balance, total_sells, total_trades, realized_pnl
        for lvl in levels:
            for held in lvl.positions:
                quote_received = _round_down(held * price, quote_dp)
                profit = quote_received - quote_per_level
                quote_balance += quote_received
                total_sells += 1
                total_trades += 1
                realized_pnl += profit
                trade_log.append(f"{tag} SELL {held} @ {price} (pnl {profit})")
            lvl.positions = []

    def _buy_pass(candle: Candle) -> None:
        nonlocal quote_balance, total_buys, total_trades
        for lvl in levels:
            if lvl.buy_count > 0 and candle.low <= lvl.price:
                base_bought = _round_down(quote_per_level / lvl.price, base_dp)
                for _ in range(lvl.buy_count):
                    lvl.positions.append(base_bought)
                    quote_balance -= quote_per_level
                    total_buys += 1
                    total_trades += 1
                    trade_log.append(f"BUY {base_bought} @ {lvl.price}")
                lvl.buy_count = 0

    def _sell_pass(candle: Candle) -> None:
        nonlocal quote_balance, total_sells, total_trades, realized_pnl
        for i, lvl in enumerate(levels):
            if not lvl.positions or i + 1 >= len(levels):
                continue
            sell_level = levels[i + 1]
            if candle.high >= sell_level.price:
                for held in lvl.positions:
                    quote_received = _round_down(held * sell_level.price, quote_dp)
                    profit = quote_received - quote_per_level
                    lvl.buy_count += 1
                    quote_balance += quote_received
                    total_sells += 1
                    total_trades += 1
                    realized_pnl += profit
                    trade_log.append(f"SELL {held} @ {sell_level.price} (pnl {profit})")
                lvl.positions = []

    for candle in candles:
        if fixed_sl_price is not None and candle.low <= fixed_sl_price:
            _liquidate_all(fixed_sl_price, "STOP-LOSS")
            stop_loss_triggered = True
            break

        bearish = candle.open > candle.close
        for pass_fn in ((_sell_pass, _buy_pass) if bearish else (_buy_pass, _sell_pass)):
            pass_fn(candle)

        if trailing_up:
            upper = levels[-1].price
            lower = levels[0].price
            grid_ratio = (upper / lower) ** (Decimal(1) / (len(levels) - 1))
            trigger = (upper * grid_ratio + upper * grid_ratio**2) / 2
            if candle.high >= trigger:
                rebuild_price = candle.close
                saved_buy_counts = [lvl.buy_count for lvl in levels]
                _liquidate_all(rebuild_price, "TRAILING-UP")
                if split_investment:
                    k = 1
                    while upper * grid_ratio**k <= rebuild_price and k < _MAX_SHIFT_ITERATIONS:
                        k += 1
                else:
                    sell_boundary = levels[len(levels) // 2].price
                    k = len(levels) // 2 + 1
                    while sell_boundary * grid_ratio**k <= rebuild_price and k < _MAX_SHIFT_ITERATIONS:
                        k += 1
                ratio_k = grid_ratio**k
                for lvl in levels:
                    lvl.price = _round(lvl.price * ratio_k, quote_dp)
                for i, lvl in enumerate(levels):
                    if lvl.price < rebuild_price:
                        lvl.buy_count = saved_buy_counts[i] if split_investment else 1
                    else:
                        lvl.buy_count = 0
                    lvl.positions = []
                trailing_up_shifts += 1

        base_held = sum((pos for lvl in levels for pos in lvl.positions), Decimal(0))
        high_value = quote_balance + base_held * candle.high
        peak_value = max(peak_value, high_value)
        low_value = quote_balance + base_held * candle.low
        if peak_value > 0:
            drawdown = (peak_value - low_value) / peak_value
            max_drawdown = max(max_drawdown, drawdown)

    final_base = sum((pos for lvl in levels for pos in lvl.positions), Decimal(0))
    return {
        "total_trades": total_trades,
        "total_buys": total_buys,
        "total_sells": total_sells,
        "realized_pnl": realized_pnl,
        "final_base": final_base,
        "final_quote": quote_balance,
        "max_drawdown": max_drawdown,
        "trade_log": trade_log,
        "trailing_up_shifts": trailing_up_shifts,
        "stop_loss_triggered": stop_loss_triggered,
    }


def format_result(sim: dict[str, Any], candles: list[Candle], investment: Decimal, days: int) -> dict[str, Any]:
    final_price = candles[-1].close
    total_value = sim["final_quote"] + sim["final_base"] * final_price
    net_return = total_value - investment
    return_pct = (net_return / investment * 100) if investment else Decimal(0)
    try:
        annualized_pct: Decimal | None = ((1 + return_pct / 100) ** (Decimal(365) / days) - 1) * 100
    except (InvalidOperation, OverflowError):
        annualized_pct = None

    return {
        "final_price": str(final_price),
        "total_value": str(total_value),
        "net_return": str(net_return),
        "return_pct": str(return_pct),
        "annualized_pct": str(annualized_pct) if annualized_pct is not None else None,
        "max_drawdown_pct": str(sim["max_drawdown"] * 100),
        "total_trades": sim["total_trades"],
        "total_buys": sim["total_buys"],
        "total_sells": sim["total_sells"],
        "realized_pnl": str(sim["realized_pnl"]),
        "final_base": str(sim["final_base"]),
        "final_quote": str(sim["final_quote"]),
        "trailing_up_shifts": sim["trailing_up_shifts"],
        "stop_loss_triggered": sim["stop_loss_triggered"],
        "trade_log_tail": sim["trade_log"][-10:],
    }


def _format_optimize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "grid_levels_per_side": row["grid_levels_per_side"],
        "range_pct": str(row["range_pct"] * 100),
        "total_return": str(row["total_return"]),
        "return_pct": str(row["return_pct"]),
        "total_trades": row["total_trades"],
        "max_drawdown_pct": str(row["max_drawdown"] * 100),
        "profit_per_trade": str(row["profit_per_trade"]),
        "calmar_approx": str(row["calmar_approx"]),
    }


def optimize_grid_params(
    candles: list[Candle],
    grid_levels_totals: list[int],
    range_pct_options: list[Decimal],
    investment: Decimal,
    split_investment: bool,
    trailing_up: bool,
    stop_loss_price: Decimal,
    base_step: Decimal,
    quote_step: Decimal,
    top_n: int,
    days: int,
) -> dict[str, Any]:
    start_price = candles[0].open
    final_price = candles[-1].close
    results: list[dict[str, Any]] = []

    for levels_total in grid_levels_totals:
        for range_pct in range_pct_options:
            if stop_loss_price > 0:
                lowest_level = start_price * (1 - range_pct)
                if stop_loss_price >= lowest_level:
                    continue
            sim = run_backtest(
                candles, levels_total, range_pct, investment, split_investment,
                trailing_up, stop_loss_price, base_step, quote_step,
            )
            total_value = sim["final_quote"] + sim["final_base"] * final_price
            total_return = total_value - investment
            return_pct = (total_return / investment * 100) if investment else Decimal(0)
            profit_per_trade = (
                sim["realized_pnl"] / sim["total_sells"] if sim["total_sells"] else Decimal(0)
            )
            annualized_return = (return_pct / 100) * Decimal(365) / days
            calmar_approx = (
                annualized_return / sim["max_drawdown"] if sim["max_drawdown"] > 0 else annualized_return
            )
            results.append(
                {
                    "grid_levels_per_side": levels_total // 2,
                    "range_pct": range_pct,
                    "total_return": total_return,
                    "return_pct": return_pct,
                    "total_trades": sim["total_trades"],
                    "max_drawdown": sim["max_drawdown"],
                    "profit_per_trade": profit_per_trade,
                    "calmar_approx": calmar_approx,
                }
            )

    results.sort(key=lambda r: r["total_return"], reverse=True)
    combos_requested = len(grid_levels_totals) * len(range_pct_options)

    return {
        "top": [_format_optimize_row(r) for r in results[:top_n]],
        "best_by_pnl": _format_optimize_row(results[0]) if results else None,
        "best_by_calmar": _format_optimize_row(max(results, key=lambda r: r["calmar_approx"])) if results else None,
        "most_trades": _format_optimize_row(max(results, key=lambda r: r["total_trades"])) if results else None,
        "lowest_drawdown": _format_optimize_row(min(results, key=lambda r: r["max_drawdown"])) if results else None,
        "combos_evaluated": len(results),
        "combos_skipped_invalid_stop_loss": combos_requested - len(results),
    }


def _parse_int_csv(raw: Any) -> list[int]:
    return [int(part.strip()) for part in str(raw).split(",") if part.strip()]


def _parse_decimal_csv(raw: Any) -> list[Decimal]:
    return [Decimal(part.strip()) for part in str(raw).split(",") if part.strip()]


async def _run_sync(client: RevolutXClient, func, *args: Any) -> Any:
    """Run a CPU-bound backtest function off the event loop when a hass
    reference is available (always, in production); fall back to running it
    inline otherwise (e.g. a standalone script with no HA instance)."""
    if client.hass is not None:
        return await client.hass.async_add_executor_job(func, *args)
    return func(*args)


async def grid_backtest_tool(client: RevolutXClient, args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args.get("symbol", "")).strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    grid_levels = int(args.get("grid_levels", 5))
    if not 1 <= grid_levels <= 25:
        raise ValueError("grid_levels must be between 1 and 25")

    range_pct = Decimal(str(args.get("range_pct", "10"))) / 100
    if range_pct <= 0:
        raise ValueError("range_pct must be positive")

    investment = Decimal(str(args.get("investment", "1000")))
    if investment <= 0:
        raise ValueError("investment must be positive")

    resolution = str(args.get("resolution", "1m"))
    if resolution not in RESOLUTION_MINUTES:
        raise ValueError(f"Unknown resolution: {resolution}")

    days = int(args.get("days", 3))
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    split_investment = bool(args.get("split_investment", False))
    trailing_up = bool(args.get("trailing_up", False))
    stop_loss_price = Decimal(str(args.get("stop_loss_price", 0)))

    candles = await fetch_candles(client, symbol, resolution, days)
    if not candles:
        raise ValueError("No candle data found for this symbol/window")

    if stop_loss_price > 0:
        lowest_level = candles[0].open * (1 - range_pct)
        if stop_loss_price >= lowest_level:
            raise ValueError("stop_loss_price must be strictly below the lowest grid level")

    base_step, quote_step = await get_step_sizes(client, symbol)
    grid_levels_total = grid_levels * 2

    sim = await _run_sync(
        client, run_backtest, candles, grid_levels_total, range_pct, investment,
        split_investment, trailing_up, stop_loss_price, base_step, quote_step,
    )

    result = format_result(sim, candles, investment, days)
    result["symbol"] = symbol
    result["grid_levels_per_side"] = grid_levels
    result["range_pct"] = str(range_pct * 100)
    result["candles_used"] = len(candles)
    result["note"] = (
        "Historical simulation only — not a prediction of future performance."
        + (" Data window was capped to the most recent candles available." if len(candles) >= MAX_CANDLES else "")
    )
    return result


async def grid_optimize_tool(client: RevolutXClient, args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args.get("symbol", "")).strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    grid_levels_options = _parse_int_csv(args.get("grid_levels_options", "3,5,8,10,15"))
    if not grid_levels_options:
        raise ValueError("grid_levels_options must not be empty")
    for n in grid_levels_options:
        if not 1 <= n <= 25:
            raise ValueError("grid_levels_options values must be between 1 and 25")

    range_pct_options = [d / 100 for d in _parse_decimal_csv(args.get("range_pct_options", "3,5,7,10,12,15,20"))]
    if not range_pct_options:
        raise ValueError("range_pct_options must not be empty")
    for r in range_pct_options:
        if r <= 0:
            raise ValueError("range_pct_options values must be positive")

    combo_count = len(grid_levels_options) * len(range_pct_options)
    if combo_count > MAX_OPTIMIZE_COMBOS:
        raise ValueError(
            f"Too many combinations ({combo_count}); reduce grid_levels_options/"
            f"range_pct_options so their product is <= {MAX_OPTIMIZE_COMBOS}."
        )

    investment = Decimal(str(args.get("investment", "1000")))
    if investment <= 0:
        raise ValueError("investment must be positive")

    resolution = str(args.get("resolution", "1m"))
    if resolution not in RESOLUTION_MINUTES:
        raise ValueError(f"Unknown resolution: {resolution}")

    days = int(args.get("days", 3))
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    split_investment = bool(args.get("split_investment", False))
    trailing_up = bool(args.get("trailing_up", False))
    stop_loss_price = Decimal(str(args.get("stop_loss_price", 0)))
    top_n = max(1, min(50, int(args.get("top_n", 10))))

    candles = await fetch_candles(client, symbol, resolution, days)
    if not candles:
        raise ValueError("No candle data found for this symbol/window")

    base_step, quote_step = await get_step_sizes(client, symbol)
    grid_levels_totals = [n * 2 for n in grid_levels_options]

    result = await _run_sync(
        client, optimize_grid_params, candles, grid_levels_totals, range_pct_options,
        investment, split_investment, trailing_up, stop_loss_price, base_step,
        quote_step, top_n, days,
    )

    result["symbol"] = symbol
    result["candles_used"] = len(candles)
    result["note"] = "Historical simulation only — not a prediction of future performance."
    return result
