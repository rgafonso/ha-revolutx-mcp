"""DataUpdateCoordinator for price-alert rules (subentries) — deliberately
separate from RevolutXDataUpdateCoordinator (account-data polling), since
alert checks want a much shorter interval (seconds, not minutes).

Rules are read from `entry.subentries` once at construction time, not
diffed on every tick: any subentry add/update/remove already triggers a full
entry reload via this integration's existing `entry.add_update_listener`
(see `__init__.py`) — HA core's subentry CRUD (`async_add_subentry`/
`async_update_subentry`/`async_remove_subentry`) already routes through
`_async_update_entry`, which fires that same listener, so a fresh coordinator
with the current rule set is built on every change. Deliberately NOT using
the newer `ConfigSubentryFlow.async_update_reload_and_abort()` for this —
mixing it with an existing `entry.add_update_listener` is deprecated as of
HA 2026.6 (will hard-error in 2026.12).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import alert_indicators as ind
from .backtest import Candle, fetch_candles
from .const import (
    CONF_ALERT_CHECK_INTERVAL,
    CONF_BAND,
    CONF_DIRECTION,
    CONF_FAST_PERIOD,
    CONF_INDICATOR,
    CONF_LOOKBACK,
    CONF_MULTIPLIER,
    CONF_NOTIFY_TARGET,
    CONF_PAIR,
    CONF_PERIOD,
    CONF_SIGNAL_PERIOD,
    CONF_SLOW_PERIOD,
    CONF_STD_MULT,
    CONF_THRESHOLD,
    DEFAULT_ALERT_CHECK_INTERVAL_SECONDS,
    DOMAIN,
    INDICATOR_ATR_BREAKOUT,
    INDICATOR_BOLLINGER,
    INDICATOR_EMA_CROSS,
    INDICATOR_MACD,
    INDICATOR_OBI,
    INDICATOR_PRICE,
    INDICATOR_PRICE_CHANGE,
    INDICATOR_RSI,
    INDICATOR_SPREAD,
    INDICATOR_VOLUME_SPIKE,
    SUBENTRY_TYPE_ALERT_RULE,
)
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient

_LOGGER = logging.getLogger(__name__)

# Indicators needing 1h candle history vs. just the live ticker/order book.
_CANDLE_INDICATORS = {
    INDICATOR_PRICE_CHANGE,
    INDICATOR_RSI,
    INDICATOR_EMA_CROSS,
    INDICATOR_MACD,
    INDICATOR_BOLLINGER,
    INDICATOR_VOLUME_SPIKE,
    INDICATOR_ATR_BREAKOUT,
}


@dataclass
class AlertRuleState:
    subentry_id: str
    title: str
    triggered: bool = False
    detail: str = ""
    last_triggered: datetime | None = None


def _needs_candles(indicator: str) -> bool:
    return indicator in _CANDLE_INDICATORS


def _candles_needed(indicator: str, data: Any) -> int:
    """How many 1h candles this rule needs at minimum, for sizing the fetch window."""
    if indicator == INDICATOR_PRICE_CHANGE:
        return int(data[CONF_LOOKBACK]) + 1
    if indicator == INDICATOR_RSI:
        return int(data[CONF_PERIOD]) + 1
    if indicator == INDICATOR_EMA_CROSS:
        return int(data[CONF_SLOW_PERIOD]) + 1
    if indicator == INDICATOR_MACD:
        return int(data[CONF_SLOW_PERIOD]) + int(data[CONF_SIGNAL_PERIOD]) + 1
    if indicator == INDICATOR_BOLLINGER:
        return int(data[CONF_PERIOD])
    if indicator == INDICATOR_VOLUME_SPIKE:
        return int(data[CONF_PERIOD]) + 1
    if indicator == INDICATOR_ATR_BREAKOUT:
        return int(data[CONF_PERIOD]) + 1
    return 24


class RevolutXAlertCoordinator(DataUpdateCoordinator[dict[str, AlertRuleState]]):
    """Polls tickers/candles/order-books for every pair referenced by an
    alert-rule subentry, evaluates each rule, and dispatches a notification
    on the not-met -> met transition (edge-triggered, matching the upstream
    CLI's own debounce semantics — a condition that stays true doesn't
    re-notify every tick)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: RevolutXClient) -> None:
        seconds = entry.options.get(CONF_ALERT_CHECK_INTERVAL, DEFAULT_ALERT_CHECK_INTERVAL_SECONDS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}_alerts",
            update_interval=timedelta(seconds=seconds),
        )
        self._client = client
        self._rules = [
            sub for sub in entry.subentries.values() if sub.subentry_type == SUBENTRY_TYPE_ALERT_RULE
        ]
        self._triggered: dict[str, bool] = {}

    async def _async_update_data(self) -> dict[str, AlertRuleState]:
        if not self._rules:
            return {}

        tickers, candles_by_pair, obi_by_pair = await self._fetch_market_data()

        result: dict[str, AlertRuleState] = {}
        newly_triggered: list[tuple[ConfigSubentry, str]] = []
        for rule in self._rules:
            state, just_triggered = self._evaluate_rule(rule, tickers, candles_by_pair, obi_by_pair)
            result[rule.subentry_id] = state
            if just_triggered:
                newly_triggered.append((rule, state.detail))

        for rule, detail in newly_triggered:
            await self._notify(rule, detail)

        return result

    async def _fetch_market_data(
        self,
    ) -> tuple[dict[str, dict[str, Decimal]], dict[str, list[Candle]], dict[str, tuple[Decimal, Decimal]]]:
        pairs = {str(rule.data[CONF_PAIR]) for rule in self._rules}
        tickers: dict[str, dict[str, Decimal]] = {}
        candles_by_pair: dict[str, list[Candle]] = {}
        obi_by_pair: dict[str, tuple[Decimal, Decimal]] = {}

        for pair in pairs:
            rules_for_pair = [r for r in self._rules if r.data[CONF_PAIR] == pair]

            try:
                ticker_resp = await self._client.get_tickers(symbols=pair)
                ticker_data = (ticker_resp or {}).get("data") or []
                if ticker_data:
                    t = ticker_data[0]
                    tickers[pair] = {
                        "mid": Decimal(str(t["mid"])),
                        "bid": Decimal(str(t["bid"])),
                        "ask": Decimal(str(t["ask"])),
                    }
            except (RevolutXAuthError, RevolutXAPIError, KeyError, TypeError, InvalidOperation) as err:
                _LOGGER.warning("Alert monitoring: could not fetch ticker for %s: %s", pair, err)

            if any(_needs_candles(r.data[CONF_INDICATOR]) for r in rules_for_pair):
                window = max(
                    (
                        _candles_needed(r.data[CONF_INDICATOR], r.data)
                        for r in rules_for_pair
                        if _needs_candles(r.data[CONF_INDICATOR])
                    ),
                    default=24,
                )
                days = max(2, (window // 24) + 2)
                try:
                    candles_by_pair[pair] = await fetch_candles(self._client, pair, "1h", days)
                except (RevolutXAuthError, RevolutXAPIError) as err:
                    _LOGGER.warning("Alert monitoring: could not fetch candles for %s: %s", pair, err)

            if any(r.data[CONF_INDICATOR] == INDICATOR_OBI for r in rules_for_pair):
                try:
                    ob_resp = await self._client.get_order_book(pair, limit=20)
                    levels = (ob_resp or {}).get("data") or {}
                    bid_volume = sum(
                        (Decimal(str(lvl["q"])) for lvl in levels.get("bids", [])), Decimal(0)
                    )
                    ask_volume = sum(
                        (Decimal(str(lvl["q"])) for lvl in levels.get("asks", [])), Decimal(0)
                    )
                    obi_by_pair[pair] = (bid_volume, ask_volume)
                except (RevolutXAuthError, RevolutXAPIError, KeyError, TypeError, InvalidOperation) as err:
                    _LOGGER.warning("Alert monitoring: could not fetch order book for %s: %s", pair, err)

        return tickers, candles_by_pair, obi_by_pair

    def _evaluate_rule(
        self,
        rule: ConfigSubentry,
        tickers: dict[str, dict[str, Decimal]],
        candles_by_pair: dict[str, list[Candle]],
        obi_by_pair: dict[str, tuple[Decimal, Decimal]],
    ) -> tuple[AlertRuleState, bool]:
        pair = str(rule.data[CONF_PAIR])
        indicator = rule.data[CONF_INDICATOR]
        ticker = tickers.get(pair)
        candles = candles_by_pair.get(pair, [])
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]
        outcome: tuple[bool, str] | None = None

        if indicator == INDICATOR_PRICE and ticker:
            outcome = ind.evaluate_price(ticker["mid"], rule.data[CONF_DIRECTION], Decimal(str(rule.data[CONF_THRESHOLD])))
        elif indicator == INDICATOR_PRICE_CHANGE and ticker:
            outcome = ind.evaluate_price_change(
                ticker["mid"], closes, rule.data[CONF_DIRECTION],
                Decimal(str(rule.data[CONF_THRESHOLD])), int(rule.data[CONF_LOOKBACK]),
            )
        elif indicator == INDICATOR_RSI:
            outcome = ind.evaluate_rsi(
                closes, rule.data[CONF_DIRECTION], Decimal(str(rule.data[CONF_THRESHOLD])), int(rule.data[CONF_PERIOD])
            )
        elif indicator == INDICATOR_EMA_CROSS:
            outcome = ind.evaluate_ema_cross(
                closes, rule.data[CONF_DIRECTION], int(rule.data[CONF_FAST_PERIOD]), int(rule.data[CONF_SLOW_PERIOD])
            )
        elif indicator == INDICATOR_MACD:
            outcome = ind.evaluate_macd(
                closes, rule.data[CONF_DIRECTION], int(rule.data[CONF_FAST_PERIOD]),
                int(rule.data[CONF_SLOW_PERIOD]), int(rule.data[CONF_SIGNAL_PERIOD]),
            )
        elif indicator == INDICATOR_BOLLINGER and ticker:
            outcome = ind.evaluate_bollinger(
                ticker["mid"], closes, rule.data[CONF_BAND], int(rule.data[CONF_PERIOD]),
                Decimal(str(rule.data[CONF_STD_MULT])),
            )
        elif indicator == INDICATOR_VOLUME_SPIKE:
            outcome = ind.evaluate_volume_spike(
                volumes, Decimal(str(rule.data[CONF_MULTIPLIER])), int(rule.data[CONF_PERIOD])
            )
        elif indicator == INDICATOR_SPREAD and ticker:
            outcome = ind.evaluate_spread(
                ticker["bid"], ticker["ask"], rule.data[CONF_DIRECTION], Decimal(str(rule.data[CONF_THRESHOLD]))
            )
        elif indicator == INDICATOR_OBI and pair in obi_by_pair:
            bid_volume, ask_volume = obi_by_pair[pair]
            outcome = ind.evaluate_obi(
                bid_volume, ask_volume, rule.data[CONF_DIRECTION], Decimal(str(rule.data[CONF_THRESHOLD]))
            )
        elif indicator == INDICATOR_ATR_BREAKOUT and ticker:
            outcome = ind.evaluate_atr_breakout(
                ticker["mid"], closes, highs, lows, Decimal(str(rule.data[CONF_MULTIPLIER])), int(rule.data[CONF_PERIOD])
            )

        was_triggered = self._triggered.get(rule.subentry_id, False)
        met = bool(outcome[0]) if outcome else False
        detail = outcome[1] if outcome else "Not enough data yet"
        self._triggered[rule.subentry_id] = met

        state = AlertRuleState(subentry_id=rule.subentry_id, title=rule.title, triggered=met, detail=detail)
        just_triggered = met and not was_triggered
        if just_triggered:
            state.last_triggered = dt_util.utcnow()
        return state, just_triggered

    async def _notify(self, rule: ConfigSubentry, detail: str) -> None:
        target = rule.data.get(CONF_NOTIFY_TARGET)
        if not target:
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": target, "message": f"{rule.title}: {detail}"},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - a bad/removed notify target shouldn't crash the coordinator
            _LOGGER.exception("Failed to send alert notification for %s", rule.title)
