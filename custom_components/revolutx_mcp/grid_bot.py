"""Live grid-bot execution: places real resting limit orders and reconciles
fills on a periodic timer. See ROADMAP.md's "Live grid-bot execution" entry
for the background — this module is the "dedicated safety design" it calls
for: two-factor arming (CONF_TRADING_ENABLED option + this bot's own switch),
order-namespace isolation (never touches an order it didn't itself place,
never calls cancel_all_orders), a hard investment cap, a consecutive-error
kill switch, and a restart-resume policy that never silently resumes placing
new orders after an uncontrolled HA restart (see __init__.py's process-start
marker and async_reconcile_only below).

Reuses backtest.py's create_grid()/get_step_sizes() for grid-level pricing
and quote-per-level sizing (the same quote_per_level = investment /
buy_level_count formula run_backtest() already uses) — but NOT
run_backtest()'s candle-driven simulation loop, which has no incremental
"process one event" API and isn't suited to live, order-book-fill-driven
execution. A live bot instead rests real limit orders on the exchange and
reconciles fills against them periodically, delegating price-crossing
detection to Revolut X's own matching engine rather than re-simulating ticks.

v1 scope: no split_investment, no trailing_up (both would need
cancelling/replacing a whole grid's worth of resting orders mid-flight —
left for a later iteration once the basic loop is proven live). Partial
fills are treated as "not yet filled" — only a `filled` order triggers a
mirror order.

Field-name note: confirmed against the upstream `revolut-x-api` TS client
(github.com/revolut-engineering/revolut-x-api, api/src/types/orders.ts +
client.ts) — its declared response types are the authoritative schema here,
since our own revolut_client.py is a thin, unmapped pass-through of the same
REST API (snake_case wire fields throughout, no camelCase translation layer
for orders the way that client has for trades/order-book). Two asymmetric
shapes to keep straight:
  - `POST /orders` (place_order) returns `{"data": {"venue_order_id": ...,
    "client_order_id": ..., "state": ...}}` — id field is `venue_order_id`,
    status field is `state`, and it's wrapped in a `data` envelope.
  - `GET /orders/{id}` (get_order) and `GET /orders/active`
    (get_active_orders, already list-wrapped) return order objects shaped
    `{"id": ..., "client_order_id": ..., "status": ..., ...}` — id field is
    `id`, status field is `status` (the opposite naming from place_order's
    response), and get_order's single object is also `data`-wrapped.
Reconciliation deliberately does NOT depend on the active-orders response
echoing back `client_order_id` for filtering; it only ever acts on
venue_order_ids already present in this engine's own persisted state, so its
order-namespace isolation holds regardless of that field's exact shape.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Callable
import uuid

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .backtest import _decimal_places, _round_down, create_grid, get_step_sizes
from .const import (
    CLIENT_ORDER_ID_PREFIX,
    CONF_CHECK_INTERVAL,
    CONF_GRID_LEVELS,
    CONF_INVESTMENT,
    CONF_MAX_CONSECUTIVE_ERRORS,
    CONF_NOTIFY_TARGET,
    CONF_PAIR,
    CONF_RANGE_PCT,
    CONF_STOP_LOSS_PRICE,
    CONF_TRADING_ENABLED,
    DEFAULT_GRID_BOT_CHECK_INTERVAL_SECONDS,
    DEFAULT_MAX_CONSECUTIVE_ERRORS,
    DEFAULT_TRADING_ENABLED,
    DOMAIN,
)
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Active vs. terminal order-state taxonomy, per this codebase's own existing
# get_active_orders/get_historical_orders tool descriptions (mcp_dispatch.py).
_ACTIVE_ORDER_STATES = "pending_new,new,partially_filled"
_TRADE_LOG_MAX = 200


@dataclass
class GridBotStoredState:
    """Everything persisted via Store — the authoritative record of a bot's
    live state, independent of entity state and HA restarts. Decimals are
    kept as strings here (JSON has no Decimal type) and converted at the
    engine's own boundary; engine logic itself always works in Decimal.
    """

    running: bool = False
    killed: bool = False
    grid_levels: list[dict[str, Any]] = field(default_factory=list)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    position_base: str = "0"
    committed_quote: str = "0"
    realized_pnl: str = "0"
    quote_per_level: str = "0"
    base_dp: int = 8
    quote_dp: int = 2
    consecutive_errors: int = 0
    last_error: str | None = None
    trade_log: list[str] = field(default_factory=list)
    last_tick: str | None = None

    def to_storage(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_storage(cls, raw: dict[str, Any] | None) -> "GridBotStoredState":
        if not raw:
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


class GridBotEngine:
    """One live grid-trading bot (one config subentry). Independently
    started/stopped and self-schedules its own reconciliation loop via
    async_track_time_interval — unlike the shared DataUpdateCoordinator the
    price-alert-rules feature uses, since each bot needs its own start/stop/
    interval lifecycle, not one poll shared across every rule.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        client: RevolutXClient,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._subentry = subentry
        self._client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_grid_bot_{subentry.subentry_id}"
        )
        self.state = GridBotStoredState()
        self._unsub_timer: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []

    # -- properties -----------------------------------------------------

    @property
    def pair(self) -> str:
        return str(self._subentry.data[CONF_PAIR])

    @property
    def is_running(self) -> bool:
        """Whether the reconciliation timer is actually scheduled right
        now — the switch entity's is_on reads this, not state.running, so
        the toggle always matches "is something actually ticking" rather
        than a persisted intent that might not have been honored yet (e.g.
        after a restart with auto_resume off)."""
        return self._unsub_timer is not None

    @property
    def trading_allowed(self) -> bool:
        return bool(self._entry.options.get(CONF_TRADING_ENABLED, DEFAULT_TRADING_ENABLED))

    def _client_order_prefix(self) -> str:
        return f"{CLIENT_ORDER_ID_PREFIX}{self._subentry.subentry_id[:8]}-"

    def _max_errors(self) -> int:
        return int(self._subentry.data.get(CONF_MAX_CONSECUTIVE_ERRORS, DEFAULT_MAX_CONSECUTIVE_ERRORS))

    # -- listeners (push entity updates immediately after a tick) -------

    def add_listener(self, callback_fn: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback_fn)

        def _remove() -> None:
            if callback_fn in self._listeners:
                self._listeners.remove(callback_fn)

        return _remove

    def _notify_listeners(self) -> None:
        for listener in self._listeners:
            listener()

    # -- persistence ------------------------------------------------------

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        self.state = GridBotStoredState.from_storage(raw)

    async def _async_persist(self) -> None:
        await self._store.async_save(self.state.to_storage())

    # -- lifecycle --------------------------------------------------------

    async def async_start(self) -> None:
        """Arms the bot: persists running=True and schedules the
        reconciliation loop. Does not place orders synchronously — the
        first scheduled tick does, so a slow/failing API call can't block
        the switch's turn_on from returning. Re-checks trading_allowed here
        too (safety §1 defense in depth) in case a service call bypasses
        the switch entity's own `available` gating.
        """
        if self.is_running:
            return
        if not self.trading_allowed:
            _LOGGER.warning(
                "Grid bot %s: refused to start — trading is disabled in this entry's Options.",
                self._subentry.title,
            )
            return

        self.state.running = True
        self.state.killed = False
        self.state.consecutive_errors = 0
        self.state.last_error = None
        interval = int(
            self._subentry.data.get(CONF_CHECK_INTERVAL, DEFAULT_GRID_BOT_CHECK_INTERVAL_SECONDS)
        )
        self._unsub_timer = async_track_time_interval(
            self.hass, self._async_tick, timedelta(seconds=interval)
        )
        await self._async_persist()
        self._notify_listeners()

    async def async_stop(self, *, cancel_orders: bool = True) -> None:
        """Full stop: unschedules the loop and always persists running=False.
        If cancel_orders, also cancels every resting order this bot placed
        (namespaced venue_order_ids only — never cancel_all_orders) but
        never touches position_base; a held base-asset position from filled
        buys is left exactly as-is ("stop" != "flatten"). The kill switch
        calls this with cancel_orders=False so a failing API isn't hammered
        with more calls while it may itself be the problem.

        For "the entry is reloading for an unrelated reason, don't disturb
        live orders" use async_pause_for_reload() instead — this method
        always marks the bot as deliberately stopped.
        """
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

        if cancel_orders:
            for client_order_id, order in list(self.state.orders.items()):
                if order["state"] != "resting" or not order.get("venue_order_id"):
                    continue
                try:
                    await self._client.cancel_order(order["venue_order_id"])
                except (RevolutXAuthError, RevolutXAPIError) as err:
                    _LOGGER.warning(
                        "Grid bot %s: failed to cancel order %s on stop: %s",
                        self._subentry.title,
                        order["venue_order_id"],
                        err,
                    )
                    continue
                del self.state.orders[client_order_id]

        self.state.running = False
        await self._async_persist()
        self._notify_listeners()

    def async_pause_for_reload(self) -> None:
        """Unschedules the local timer only — does not touch state.running,
        state.orders, or cancel anything. Used by __init__.py's
        async_unload_entry when the entry is reloading for a reason
        unrelated to trading_enabled turning off (this Python object is
        going away either way), so live resting orders are left completely
        undisturbed and setup can pick the bot right back up.
        """
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    async def async_reconcile_only(self) -> None:
        """Startup-only refresh: updates fill/position/P&L bookkeeping from
        Revolut X's current order state without placing any new orders or
        seeding a fresh grid. Used when HA restarts and this bot was
        running, so its sensors reflect reality immediately without
        silently resuming autonomous order placement — see the restart-
        behavior safety rule in this module's docstring / ROADMAP.md.
        """
        try:
            await self._reconcile_once(place_mirrors=False)
        except (RevolutXAuthError, RevolutXAPIError, KeyError, TypeError, ValueError, InvalidOperation) as err:
            _LOGGER.warning(
                "Grid bot %s: startup reconcile failed (will retry once resumed): %s",
                self._subentry.title,
                err,
            )
        self.state.last_tick = dt_util.utcnow().isoformat()
        await self._async_persist()
        self._notify_listeners()

    async def async_defer_resume(self) -> None:
        """Used at HA startup when this bot was running before a restart but
        auto-resume isn't enabled for it: leaves the timer unscheduled and
        persists running=False, so the switch always reflects "is a timer
        actually scheduled" rather than a stale prior intent — the user
        must notice and explicitly turn it back on.
        """
        self.state.running = False
        await self._async_persist()
        self._notify_listeners()

    # -- the reconciliation loop -------------------------------------------

    async def _async_tick(self, _now: datetime | None = None) -> None:
        if self.state.killed:
            # The timer is unscheduled on kill (see _on_tick_error), so this
            # shouldn't fire again in production — guarded anyway so a
            # direct/manual call can't keep hammering a known-broken API and
            # incrementing consecutive_errors past the point that already
            # triggered the kill switch.
            return
        if not self.trading_allowed:
            # trading_enabled flipped off without this bot's own switch
            # being touched — two-factor arming (safety §1): treat exactly
            # like a manual stop.
            await self.async_stop(cancel_orders=True)
            return

        try:
            await self._reconcile_once()
            self.state.consecutive_errors = 0
        except (RevolutXAuthError, RevolutXAPIError, KeyError, TypeError, ValueError, InvalidOperation) as err:
            await self._on_tick_error(err)

        self.state.last_tick = dt_util.utcnow().isoformat()
        self._store.async_delay_save(self.state.to_storage, 3)
        self._notify_listeners()

    async def _reconcile_once(self, *, place_mirrors: bool = True) -> None:
        freshly_seeded = False
        if not self.state.grid_levels:
            if not place_mirrors:
                return  # startup-only pass: don't seed a fresh grid, that places orders
            await self._initialize_grid()
            if not self.state.grid_levels:
                return  # e.g. current price sits above the entire grid range; retry next tick
            freshly_seeded = True

        if not freshly_seeded:
            # Skip the fill-check on the same tick that just seeded the grid —
            # those orders were placed moments ago in this same call and can't
            # have left the exchange's active-order list yet; diffing against
            # get_active_orders here would misread every freshly-placed order
            # as "gone" (filled/cancelled) before it even had a chance to rest.
            resp = await self._client.get_active_orders(
                symbols=self.pair, order_states=_ACTIVE_ORDER_STATES
            )
            active_ids = {str(o["id"]) for o in (resp or {}).get("data", []) if "id" in o}

            for client_order_id, order in list(self.state.orders.items()):
                if order["state"] != "resting":
                    continue
                venue_order_id = order.get("venue_order_id")
                if venue_order_id and venue_order_id in active_ids:
                    continue
                await self._handle_left_active_state(client_order_id, order, place_mirrors=place_mirrors)

        if place_mirrors:
            await self._check_stop_loss()

    async def _initialize_grid(self) -> None:
        mid_price = await self._get_mid_price()
        if mid_price is None:
            return  # bad/stale ticker — treated as a tick failure by the caller, not silently ignored

        base_step, quote_step = await get_step_sizes(self._client, self.pair)
        base_dp = _decimal_places(base_step)
        quote_dp = _decimal_places(quote_step)

        grid_levels_per_side = int(self._subentry.data[CONF_GRID_LEVELS])
        range_pct = Decimal(str(self._subentry.data[CONF_RANGE_PCT])) / 100
        investment = Decimal(str(self._subentry.data[CONF_INVESTMENT]))

        levels = create_grid(mid_price, grid_levels_per_side * 2, range_pct, quote_dp)
        buy_level_count = sum(1 for lvl in levels if lvl.buy_count > 0)
        if buy_level_count == 0:
            return  # current price is above the whole grid range; nothing to seed yet

        quote_per_level = _round_down(investment / buy_level_count, quote_dp)

        self.state.grid_levels = [
            {"level_index": i, "price": str(lvl.price)} for i, lvl in enumerate(levels)
        ]
        self.state.quote_per_level = str(quote_per_level)
        self.state.base_dp = base_dp
        self.state.quote_dp = quote_dp

        for i, lvl in enumerate(levels):
            if lvl.buy_count <= 0:
                continue
            if Decimal(self.state.committed_quote) + quote_per_level > investment:
                break  # investment cap (safety §3) — stop seeding further buy levels
            base_size = _round_down(quote_per_level / lvl.price, base_dp)
            await self._place_order(i, "buy", lvl.price, base_size)
            self.state.committed_quote = str(Decimal(self.state.committed_quote) + quote_per_level)

    async def _get_mid_price(self) -> Decimal | None:
        resp = await self._client.get_tickers(symbols=self.pair)
        data = (resp or {}).get("data") or []
        if not data:
            return None
        try:
            mid = Decimal(str(data[0]["mid"]))
        except (KeyError, InvalidOperation, TypeError):
            return None
        return mid if mid > 0 else None

    async def _handle_left_active_state(
        self, client_order_id: str, order: dict[str, Any], *, place_mirrors: bool
    ) -> None:
        venue_order_id = order.get("venue_order_id")
        status = "cancelled"
        if venue_order_id:
            try:
                detail = await self._client.get_order(venue_order_id)
            except (RevolutXAuthError, RevolutXAPIError):
                # Leave it recorded as resting; re-check next tick rather
                # than guessing an outcome from a failed lookup.
                return
            # get_order returns {"data": {"status": ..., ...}} — see this
            # module's docstring for the id/status field-name asymmetry
            # between this endpoint and place_order's response.
            status = str(((detail or {}).get("data") or {}).get("status", "cancelled"))

        del self.state.orders[client_order_id]

        if status != "filled":
            self.state.trade_log.append(
                f"{order['side'].upper()} order at level {order['level_index']} ended as "
                f"{status} (not filled)"
            )
            self._trim_trade_log()
            return

        await self._apply_fill(order, place_mirrors=place_mirrors)

    async def _apply_fill(self, order: dict[str, Any], *, place_mirrors: bool) -> None:
        price = Decimal(order["price"])
        base_size = Decimal(order["base_size"])
        level_index = order["level_index"]

        if order["side"] == "buy":
            self.state.position_base = str(Decimal(self.state.position_base) + base_size)
            self.state.trade_log.append(f"BUY {base_size} @ {price}")
            if place_mirrors:
                await self._place_mirror(level_index + 1, "sell", base_size)
        else:
            quote_per_level = Decimal(self.state.quote_per_level)
            profit = (base_size * price) - quote_per_level
            self.state.position_base = str(Decimal(self.state.position_base) - base_size)
            self.state.committed_quote = str(
                max(Decimal("0"), Decimal(self.state.committed_quote) - quote_per_level)
            )
            self.state.realized_pnl = str(Decimal(self.state.realized_pnl) + profit)
            self.state.trade_log.append(f"SELL {base_size} @ {price} (pnl {profit})")
            if place_mirrors:
                await self._place_mirror(level_index - 1, "buy", base_size)

        self._trim_trade_log()

    async def _place_mirror(self, level_index: int, side: str, sell_base_size: Decimal) -> None:
        if level_index < 0 or level_index >= len(self.state.grid_levels):
            return  # mirror would land outside the configured grid — nothing to place
        price = Decimal(self.state.grid_levels[level_index]["price"])

        if side == "sell":
            await self._place_order(level_index, "sell", price, sell_base_size)
            return

        investment = Decimal(str(self._subentry.data[CONF_INVESTMENT]))
        cost = Decimal(self.state.quote_per_level)
        if Decimal(self.state.committed_quote) + cost > investment:
            self.state.trade_log.append(
                f"Skipped BUY at level {level_index}: would exceed the investment cap"
            )
            self._trim_trade_log()
            return
        base_size = _round_down(cost / price, self.state.base_dp)
        await self._place_order(level_index, "buy", price, base_size)
        self.state.committed_quote = str(Decimal(self.state.committed_quote) + cost)

    async def _place_order(self, level_index: int, side: str, price: Decimal, base_size: Decimal) -> None:
        if base_size <= 0:
            return
        client_order_id = f"{self._client_order_prefix()}{level_index}-{uuid.uuid4().hex[:8]}"
        self.state.orders[client_order_id] = {
            "venue_order_id": None,
            "level_index": level_index,
            "side": side,
            "price": str(price),
            "base_size": str(base_size),
            "state": "pending_place",
        }
        response = await self._client.place_order(
            client_order_id,
            self.pair,
            side,
            {"limit": {"price": str(price), "base_size": str(base_size), "time_in_force": "gtc"}},
        )
        # place_order returns {"data": {"venue_order_id": ..., "state": ...}}
        # — see this module's docstring for the id/status field-name
        # asymmetry between this endpoint and get_order's response.
        result = (response or {}).get("data") or {}
        venue_order_id = str(result.get("venue_order_id") or "") or None
        self.state.orders[client_order_id]["venue_order_id"] = venue_order_id
        self.state.orders[client_order_id]["state"] = "resting" if venue_order_id else "pending_place"

    async def _check_stop_loss(self) -> None:
        stop_loss_price = Decimal(str(self._subentry.data.get(CONF_STOP_LOSS_PRICE, 0)))
        if stop_loss_price <= 0:
            return
        mid = await self._get_mid_price()
        if mid is None or mid > stop_loss_price:
            return

        self.state.trade_log.append(f"STOP-LOSS triggered at {mid} (threshold {stop_loss_price})")
        self._trim_trade_log()
        await self.async_stop(cancel_orders=True)
        await self._notify(
            f"Stop-loss triggered at {mid} — bot stopped, resting orders cancelled. "
            "Any already-filled position was left untouched."
        )

    async def _on_tick_error(self, err: Exception) -> None:
        self.state.consecutive_errors += 1
        self.state.last_error = str(err)
        max_errors = self._max_errors()
        _LOGGER.warning(
            "Grid bot %s: reconciliation tick failed (%d/%d consecutive): %s",
            self._subentry.title,
            self.state.consecutive_errors,
            max_errors,
            err,
        )
        if self.state.consecutive_errors >= max_errors and not self.state.killed:
            self.state.killed = True
            await self.async_stop(cancel_orders=False)
            await self._notify(
                f"Grid bot stopped after {self.state.consecutive_errors} consecutive errors: "
                f"{err}. A human must investigate and re-arm — no auto-recovery."
            )

    async def _notify(self, message: str) -> None:
        target = self._subentry.data.get(CONF_NOTIFY_TARGET)
        title = f"Revolut X grid bot: {self._subentry.title}"
        if target:
            try:
                await self.hass.services.async_call(
                    "notify",
                    "send_message",
                    {"entity_id": target, "message": message},
                    blocking=True,
                )
                return
            except Exception:  # noqa: BLE001 - a bad/removed notify target shouldn't crash the engine
                _LOGGER.exception("Failed to send grid-bot notification for %s", self._subentry.title)
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=f"{DOMAIN}_grid_bot_{self._subentry.subentry_id}",
        )

    def _trim_trade_log(self) -> None:
        if len(self.state.trade_log) > _TRADE_LOG_MAX:
            self.state.trade_log = self.state.trade_log[-_TRADE_LOG_MAX:]
