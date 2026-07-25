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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .alert_indicators import evaluate_price, evaluate_price_change, evaluate_rsi
from .backtest import fetch_candles
from .const import (
    CONF_ALERT_CHECK_INTERVAL,
    CONF_DIRECTION,
    CONF_INDICATOR,
    CONF_LOOKBACK,
    CONF_NOTIFY_TARGET,
    CONF_PAIR,
    CONF_PERIOD,
    CONF_THRESHOLD,
    DEFAULT_ALERT_CHECK_INTERVAL_SECONDS,
    DOMAIN,
    INDICATOR_PRICE,
    INDICATOR_PRICE_CHANGE,
    INDICATOR_RSI,
    SUBENTRY_TYPE_ALERT_RULE,
)
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class AlertRuleState:
    subentry_id: str
    title: str
    triggered: bool = False
    detail: str = ""
    last_triggered: datetime | None = None


def _needs_candles(indicator: str) -> bool:
    return indicator in (INDICATOR_PRICE_CHANGE, INDICATOR_RSI)


class RevolutXAlertCoordinator(DataUpdateCoordinator[dict[str, AlertRuleState]]):
    """Polls tickers/candles for every pair referenced by an alert-rule
    subentry, evaluates each rule, and dispatches a notification on the
    not-met -> met transition (edge-triggered, matching the upstream CLI's
    own debounce semantics — a condition that stays true doesn't re-notify
    every tick)."""

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

        prices, closes_by_pair = await self._fetch_market_data()

        result: dict[str, AlertRuleState] = {}
        newly_triggered: list[tuple[ConfigSubentry, str]] = []
        for rule in self._rules:
            state, just_triggered = self._evaluate_rule(rule, prices, closes_by_pair)
            result[rule.subentry_id] = state
            if just_triggered:
                newly_triggered.append((rule, state.detail))

        for rule, detail in newly_triggered:
            await self._notify(rule, detail)

        return result

    async def _fetch_market_data(self) -> tuple[dict[str, Decimal], dict[str, list[Decimal]]]:
        pairs = {str(rule.data[CONF_PAIR]) for rule in self._rules}
        prices: dict[str, Decimal] = {}
        closes_by_pair: dict[str, list[Decimal]] = {}

        for pair in pairs:
            rules_for_pair = [r for r in self._rules if r.data[CONF_PAIR] == pair]
            needs_candles = any(_needs_candles(r.data[CONF_INDICATOR]) for r in rules_for_pair)
            try:
                ticker_resp = await self._client.get_tickers(symbols=pair)
                ticker_data = (ticker_resp or {}).get("data") or []
                if ticker_data:
                    prices[pair] = Decimal(str(ticker_data[0]["mid"]))
                if needs_candles:
                    window = max(
                        (
                            int(r.data.get(CONF_PERIOD) or r.data.get(CONF_LOOKBACK) or 24)
                            for r in rules_for_pair
                            if _needs_candles(r.data[CONF_INDICATOR])
                        ),
                        default=24,
                    )
                    days = max(2, (window // 24) + 2)
                    candles = await fetch_candles(self._client, pair, "1h", days)
                    closes_by_pair[pair] = [c.close for c in candles]
            except (RevolutXAuthError, RevolutXAPIError, KeyError, TypeError, InvalidOperation) as err:
                _LOGGER.warning("Alert monitoring: could not fetch data for %s: %s", pair, err)

        return prices, closes_by_pair

    def _evaluate_rule(
        self, rule: ConfigSubentry, prices: dict[str, Decimal], closes_by_pair: dict[str, list[Decimal]]
    ) -> tuple[AlertRuleState, bool]:
        pair = str(rule.data[CONF_PAIR])
        indicator = rule.data[CONF_INDICATOR]
        price = prices.get(pair)
        outcome: tuple[bool, str] | None = None

        if price is not None:
            if indicator == INDICATOR_PRICE:
                outcome = evaluate_price(price, rule.data[CONF_DIRECTION], Decimal(str(rule.data[CONF_THRESHOLD])))
            elif indicator == INDICATOR_PRICE_CHANGE:
                outcome = evaluate_price_change(
                    price,
                    closes_by_pair.get(pair, []),
                    rule.data[CONF_DIRECTION],
                    Decimal(str(rule.data[CONF_THRESHOLD])),
                    int(rule.data[CONF_LOOKBACK]),
                )
            elif indicator == INDICATOR_RSI:
                outcome = evaluate_rsi(
                    closes_by_pair.get(pair, []),
                    rule.data[CONF_DIRECTION],
                    Decimal(str(rule.data[CONF_THRESHOLD])),
                    int(rule.data[CONF_PERIOD]),
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
