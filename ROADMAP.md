# Roadmap

Directional only — no target versions or dates. Items move here once there's a
concrete design direction, not just an idea; they move out once implemented
(into `CHANGELOG.md`) or explicitly dropped.

Scope: `custom_components/revolutx_mcp`, the actively developed distribution.
The Supervisor add-on's own README lists price monitoring and strategy
backtesting as long-standing goals too, but the direction below is specific to
building these *inside* Home Assistant, not porting the add-on's Node/CLI
approach — see "Why not port the CLI's model" below.

## Native HA entities (service status + account/market data)

Today `PLATFORMS: list[str] = []` in `__init__.py` — this integration exposes
zero Home Assistant entities. Everything is only reachable on-demand through
an MCP tool call from an LLM conversation; there's nothing to put on a
dashboard, chart in History, or trigger an automation from. Two entity groups
worth adding:

- **Service/integration health**: entities describing this integration's own
  operation, not Revolut X data — e.g. a `binary_sensor` for whether the
  webhook/direct server is up, a sensor counting MCP requests served (plus
  last-served timestamp), and a sensor mirroring the `trading_enabled` config
  option so it's visible on a dashboard instead of buried in Options. Useful
  for noticing "my MCP server silently stopped responding" without checking
  logs.
- **Account/market data**: sensors for `get_balances` (one sensor per
  currency, or a single sensor with the full balance dict as attributes for a
  simpler first pass) and `get_active_orders` (a count sensor with the order
  list as an attribute), so these show up in dashboards/History/automations
  instead of being reachable only through a conversation. A per-symbol ticker
  sensor is a natural extension, scoped to a user-configured pair list rather
  than every tradeable pair.

Direction: reuse a `DataUpdateCoordinator` for the polling — plausibly the
*same* coordinator proposed for price-alert monitoring below, so balance/order
polling and monitor-alert evaluation share one Revolut X API call cadence
instead of polling independently. Keep the interval conservative and
user-configurable; Revolut X's documented rate limit is 1000 requests/day for
limit orders specifically, and general endpoint limits aren't fully
documented, so defaulting to minutes rather than seconds is the safer starting
point.

## Price-alert monitoring

The upstream `revx` CLI's `monitor` command group (price thresholds, RSI,
EMA-cross, MACD, Bollinger, volume-spike, spread, order-book imbalance,
price-change, ATR-breakout) has no equivalent in this integration today.

Direction if/when this gets built: use Home Assistant's own primitives instead
of replicating the CLI's architecture:

- **Polling**: a `DataUpdateCoordinator` on a configurable interval, not a
  hand-rolled `while` loop — HA already solves "periodic background work
  inside an always-on process" for us.
- **Delivery**: HA's own `notify.*` platform ecosystem (mobile app push,
  email, any of the dozens of existing notify integrations), not a
  hardcoded Telegram integration. Telegram is still available *through* HA's
  notify platform if a user wants it, for free.
- **State/persistence**: HA's own config-entry storage and entity state,
  not hand-rolled JSON files in a config directory.
- **Alert history**: represent triggered alerts as HA entities (e.g. a
  `binary_sensor` or event entity per monitor) so they show up in HA's
  existing Logbook/History for free — no separate `events` log/command needed,
  that's what the CLI's `events` command had to build by hand precisely
  because it didn't have a host platform like HA underneath it.

## Live grid-bot execution

The CLI's `revx strategy grid run` places real orders continuously,
unsupervised, persisting its position state to a local JSON file so it can
reconcile after a crash. `grid_backtest`/`grid_optimize` (added in 0.4.0) are
the read-only simulation half of this; live execution is the other half and
isn't planned yet.

This is a distinct, higher-risk category from the on-demand order-write tools
added in 0.4.0 (`place_order`/`replace_order`/`cancel_order`/
`cancel_all_orders`), which only ever act on an explicit, single tool call
inside a human-supervised conversation. An autonomously-running bot placing
orders on its own schedule needs its own dedicated safety design — not
covered by the existing `trading_enabled` toggle — before this is worth
picking up. No direction chosen yet; flagged here mainly so it isn't confused
with the simulation tools that already exist.

## Dashboard for visualization

Depends on the three items above existing first — there's nothing to
visualize until entities, monitors, and a live grid bot are actually there.
Once they are, a bundled example dashboard (or a documented Lovelace YAML
snippet in the README) tying them together would be worth adding: account
balances/orders, which monitors are currently armed and how close they are to
triggering, and grid-bot state (current price's position within the grid,
open positions, realized P&L) — the kind of view the CLI's `strategy grid run`
already renders as a live terminal dashboard.

Direction: prefer standard Lovelace cards (entities card, history-graph,
statistics card) over a custom frontend component wherever they're
expressive enough — HA already provides charting/history for free once the
underlying entities exist, so most of this may end up being a documented
dashboard config rather than code we maintain. A custom card would only be
worth building if a standard card genuinely can't represent something — a
grid-levels-vs-current-price visualization for the live bot is the most
likely candidate, mirroring the CLI's own bespoke terminal view for that same
data. No direction chosen on the custom-card question yet; it depends on how
the entities from the sections above end up shaped.

## Why not port the CLI's model

Research into `cli/src/commands/monitor.ts` and `cli/src/commands/strategy.ts`
(see conversation history / commit history around the 0.4.0 release) found
the upstream CLI's `monitor` and `strategy grid run` are foreground, blocking
Node processes with no daemonization, no process supervisor, and no
auto-restart after a crash or reboot — persistence is local JSON files
(`~/.revx`-style config dir), notifications are Telegram-only, and `events`
is just a local log reader over the same JSON file the monitor writes to.
None of that maps well onto Home Assistant, which already provides an
always-on host process, its own persistent storage, and a much broader
notification ecosystem — replicating the CLI's bespoke solutions to problems
HA already solves would be redundant, not a port worth doing faithfully.
