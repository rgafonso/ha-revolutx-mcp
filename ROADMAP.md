# Roadmap

Directional only — no target versions or dates. Items move here once there's a
concrete design direction, not just an idea; they move out once implemented
(into `CHANGELOG.md`) or explicitly dropped.

Scope: `custom_components/revolutx_mcp`, the actively developed distribution.
The Supervisor add-on's own README lists price monitoring and strategy
backtesting as long-standing goals too, but the direction below is specific to
building these *inside* Home Assistant, not porting the add-on's Node/CLI
approach — see "Why not port the CLI's model" below.

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
custom-card question below.

Live grid-bot execution (see `CHANGELOG.md`) added a switch + P&L + status
sensor per bot, each addable to the example dashboard with the same standard
tile cards as everything else — not done yet, but no new direction is
needed for that part, it's just more of the same pattern. What's still
genuinely open is a proper grid-levels-vs-current-price visualization —
current price's position within the grid, which levels are filled — the
kind of view the upstream CLI's `strategy grid run` renders as a live
terminal dashboard. The status sensor's `grid_levels` attribute already
carries the raw data a custom card would need; no direction chosen yet on
whether a standard card (e.g. a cleverly-configured gauge/bar) can represent
it well enough, or whether it's worth a bespoke card.

Direction: prefer standard Lovelace cards (entities card, history-graph,
statistics card) over a custom frontend component wherever they're
expressive enough — HA already provides charting/history for free once the
underlying entities exist, so most of this may end up being a documented
dashboard config rather than code we maintain. A custom card would only be
worth building if a standard card genuinely can't represent something, and
the grid-vs-price view above is the most likely (only remaining) candidate.

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
