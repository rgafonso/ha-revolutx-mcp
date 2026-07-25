# Roadmap

Directional only — no target versions or dates. Items move here once there's a
concrete design direction, not just an idea; they move out once implemented
(into `CHANGELOG.md`) or explicitly dropped.

Scope: `custom_components/revolutx_mcp`, the actively developed distribution.
The Supervisor add-on's own README lists price monitoring and strategy
backtesting as long-standing goals too, but the direction below is specific to
building these *inside* Home Assistant, not porting the add-on's Node/CLI
approach — see "Why not port the CLI's model" below.

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

The account/alerts half is done: `custom_components/revolutx_mcp/dashboard_example.yaml`
is a bundled example Lovelace dashboard (documented in that directory's
README under "Dashboard"), covering balances, active orders, price-alert
rule status, and service health. Standard cards (tile, heading, grid) were
sufficient for everything with a fixed entity ID; the two entity groups that
grow over time and can't be hardcoded (per-currency balance sensors,
per-alert-rule sensors named after each rule's own title) are listed
dynamically via the community `auto-entities` card instead — a filter-driven
listing card, not a bespoke visualization, so it doesn't bear on the
custom-card question below, which is specifically about whether a standard
card can represent the live grid-bot's grid-vs-price view.

What's still missing is grid-bot state (current price's position within the
grid, open positions, realized P&L) — the kind of view the CLI's
`strategy grid run` already renders as a live terminal dashboard — which
depends on live grid-bot execution (above) not implemented yet. Once that
exists, extend the example dashboard with it rather than starting a new one.

Direction: prefer standard Lovelace cards (entities card, history-graph,
statistics card) over a custom frontend component wherever they're
expressive enough — HA already provides charting/history for free once the
underlying entities exist, so most of this may end up being a documented
dashboard config rather than code we maintain. A custom card would only be
worth building if a standard card genuinely can't represent something — a
grid-levels-vs-current-price visualization for the live bot is the most
likely candidate, mirroring the CLI's own bespoke terminal view for that same
data. No direction chosen on the custom-card question yet for that
grid-bot-specific piece; it depends on how the live-execution entities end up
shaped.

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
