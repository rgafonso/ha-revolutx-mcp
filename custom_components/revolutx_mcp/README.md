# Revolut X MCP (Home Assistant custom_component)

<img src="logo.png" alt="Revolut X MCP" width="96" height="96">

An in-process Home Assistant integration that exposes read-only Revolut X market
data and account tools over MCP (Model Context Protocol) — no separate container,
no Node.js, works on Home Assistant OS, Supervised, Container, and Core.

This is a separate distribution method from this repo's Supervisor add-on
(`config.yaml`/`Dockerfile` at the repo root) — install one or the other, not both,
for a given Revolut X account.

## What it does

- Runs the Revolut X MCP tool logic (balances, orders, trades, order book, candles,
  tickers, public market data, grid-strategy backtesting, and a small help-topic
  lookup — 18 always-available tools) directly inside Home Assistant's own event
  loop, signing requests to the Revolut X API with the Ed25519 private key you
  provide.
- Order placement/modification/cancellation (4 more tools) is available but
  **off by default** — see [Trading tools (optional)](#trading-tools-optional)
  below. With it left off, this integration is read-only.
- Exposes those tools two ways: through a Home Assistant **webhook** (reachable via
  Nabu Casa remote access or any reverse proxy already pointed at your HA
  instance), and optionally through a **standalone port** for direct LAN access.
- Every tool declares MCP tool annotations (`readOnlyHint`, `destructiveHint`, etc.,
  per the MCP spec) so clients that support it — including Claude's connector
  settings screen — can separate read-only tools from the 4 trading tools in their
  own permission UI.
- Also exposes native Home Assistant entities (see [Entities](#entities) below) —
  balances, active orders, and service-health sensors — so this data shows up on
  dashboards, in History, and in automations without going through an MCP/LLM call.
- Price-alert rules (see [Price alerts](#price-alerts) below) you add/edit/remove
  entirely from the integration's own Settings page — no YAML, no MCP/LLM call
  needed to manage them. **Requires Home Assistant 2025.3.0+.**
- Bundles its own icon (`brand/icon.png`, `brand/logo.png` + `@2x` variants) using
  Home Assistant's [brands proxy API](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/)
  (HA 2026.3+) — no submission to the separate `home-assistant/brands` repo
  needed. `homeassistant.loader.Integration.has_branding` just checks for a
  `brand/` folder on disk; on HA versions older than 2026.3, the integrations
  list falls back to a generic placeholder icon instead.

## Install

1. In HACS: Integrations → ⋮ → Custom repositories → add this repo
   (`https://github.com/rgafonso/ha-revolutx-mcp`), category **Integration** → Download.
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → search **Revolut X MCP**.
4. Generate an Ed25519 keypair for Revolut X (Profile → API Keys → Generate
   keypair), add the public key to your account, create an API key. Paste the
   **API key** and the **private key PEM** into the setup form — it's validated
   with a live `GET /balances` call before the entry is created.
5. Open the integration's **Configure** screen to set the auth mode, direct-server
   port, and an external URL override if needed.

## Auth modes (Options → Authentication mode)

- **none** (default): the webhook URL / direct-server URL itself is the
  credential, same as Home Assistant's webhook component's normal behavior — no
  token to manage, keep the URL secret.
- **legacy_oauth** (recommended for OAuth-capable MCP clients, e.g. Claude): this
  integration's *own* OAuth 2.1 Authorization Code + PKCE server, with Dynamic
  Client Registration (RFC 7591) so clients that require it (Claude errors with
  `registration_endpoint_missing` otherwise) can self-register with no manual
  Client ID/Secret entry. Two things had to be worked around to make this
  reachable at all:
  - Home Assistant *core itself* permanently registers the bare
    `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource`
    (`homeassistant/components/auth/login_flow.py`, part of the always-loaded
    `auth` component) — no custom integration can win those paths, on any HA
    installation. So this integration's own metadata lives at paths scoped
    under its own issuer (`/.well-known/oauth-authorization-server/api/revolutx_mcp`,
    per RFC 8414 §3.1) and the specific protected resource
    (`/.well-known/oauth-protected-resource/api/webhook/<id>`, per RFC 9728),
    instead of the bare root.
  - The webhook's 401 response points clients at that exact URL via the
    `resource_metadata` parameter in `WWW-Authenticate` (RFC 9728 §5.2 — a
    client MUST follow this rather than guess), so a spec-compliant client
    reaches this integration's metadata directly and never needs to touch the
    HA-core-owned bare path at all.
- **ha_auth**: tokens are validated against Home Assistant's own native auth
  system (`hass.auth.async_validate_access_token`) instead — the same tokens
  HA core's `/auth/authorize` + `/auth/token` issues, or a Long-Lived Access
  Token from your HA user profile. Works for clients that already hold such a
  token, but Home Assistant's native AS has **no Dynamic Client Registration**
  (it uses IndieAuth: `client_id` must be a URL matching the client's own
  redirect URI's origin) — most generic OAuth clients, including Claude, can't
  complete that flow without help from the client's own developer. Prefer
  `legacy_oauth` unless you specifically want to reuse Home Assistant login
  sessions.

  See `oauth_legacy.py` for the full design notes and its limitations (no
  persistent client registry — DCR just mints a fresh opaque `client_id` per
  request, since PKCE is the actual security boundary).

## Connect a client

- **Webhook URL**: shown at the top of the integration's **Configure** screen, in
  a Home Assistant notification when the server starts, and in the HA log.
  Format: `<your-ha-url>/api/webhook/<webhook_id>`.
- **Direct URL** (if enabled): `http://<ha-host>:<port>/<random-path>`, shown in
  the same three places.

Paste either URL into your MCP client (e.g. a Claude Desktop custom connector).

## Trading tools (optional)

Options → **Enable order placement (trading)**, off by default. When off, the 4
tools below don't appear in the MCP client's tool list at all and calling them by
name is rejected the same way a nonexistent tool name would be. When on, they're
reachable by any MCP client connected to this integration:

- `place_order` — limit or market order.
- `replace_order` — modify price/size/time-in-force on an open order (cancels and
  re-issues it under a new venue order ID).
- `cancel_order` — cancel one open order.
- `cancel_all_orders` — cancel **every** open order on the account; there is no
  symbol filter.

There is no dry-run mode or second confirmation step beyond the toggle itself —
each tool's description asks the calling LLM to confirm the details with you
first, but that's a hint the client may or may not honor. Only enable this if you
trust the MCP client you're connecting and intend to use it for trading.

## Entities

All entities group under one HA device ("Revolut X") per config entry, and
every one of them carries a `revolut_x_category` attribute (`account`,
`health`, `order`, `monitor`, or `strategy`) — a stable way to filter or
group them (e.g. in a dashboard's `auto-entities` card, see
[Dashboard](#dashboard) below) without depending on entity_id patterns,
domain, or device membership, none of which line up cleanly with "kind of
thing" on their own.

- **Balances**: one sensor per currency held in the account (e.g. `sensor.revolut_x_btc_balance`),
  added dynamically as new currencies are first seen. State is the spendable
  ("available") amount; `reserved`/`total`/`staked` are attributes. A currency
  that disappears from a later poll goes `unavailable` rather than being removed.
- **Active orders**: a count sensor (raw order list as its attribute), plus
  one sensor per currently-open order (e.g. `sensor.revolut_x_btc_eur_buy_order`),
  added dynamically as orders are placed. State is the order's own status
  (`new`/`partially_filled`/...); price, size, filled amount, and the rest of
  the order fields are attributes. Unlike balances, an order's sensor is
  removed outright (not left `unavailable`) once it's no longer open —
  orders churn constantly as they fill/cancel, so keeping every past order
  around forever would grow the entity registry unbounded.
- **Service health**: an MCP request-count sensor and a last-request-served
  timestamp sensor (both push-updated on every successfully authenticated,
  well-formed MCP call) — these are the useful "did my server silently stop
  responding" signal. Two diagnostic binary sensors (`webhook_registered`,
  `direct_server_running`) exist too, but read their own docstrings before
  relying on them: `webhook_registered` only ever means "this config entry is
  loaded," not "reachable over the network."
- **Trading enabled**: a switch (`switch.revolut_x_trading_enabled`) that
  reads and writes the same `trading_enabled` options-flow value, so it can
  be toggled directly from a dashboard instead of only via Settings >
  Options — flipping it triggers the exact same config-entry reload either
  path already causes. Turning it off while a grid bot is running cancels
  that bot's live resting orders, same as changing it in Options today.
- **Alert rules**: one triggered/not-triggered binary sensor per price-alert
  rule you've added (see [Price alerts](#price-alerts)), named after the
  rule itself.
- **Grid bots**: one start/stop switch, one P&L sensor, and one status
  sensor per live grid bot you've added (see [Grid bots](#grid-bots)), named
  after the bot itself.

## Price alerts

From the integration's entry page (Settings → Devices & Services → Revolut X
MCP), an **"Add alert rule"** button lets you define independent alert rules
— no YAML, no code. Each rule picks one of 10 indicator types (full parity
with the upstream `revx` CLI's `monitor` command group) and gets its own
form:

- **Price threshold**: pair, direction (above/below), threshold price.
- **Price change %**: pair, direction (rise/fall), threshold %, lookback (in
  1-hour candles).
- **RSI**: pair, direction (above/below), threshold (0-100), period.
- **EMA crossover**: pair, direction (bullish/bearish), fast/slow periods.
- **MACD**: pair, direction (bullish/bearish), fast/slow/signal periods.
- **Bollinger Bands**: pair, band (upper/lower), period, stdev multiplier.
- **Volume spike**: pair, baseline period, spike multiplier (current 1h
  candle's volume vs. the average of the preceding candles).
- **Bid-ask spread**: pair, direction, threshold % (from the live ticker).
- **Order book imbalance**: pair, direction, threshold (−1..1, computed
  over the top 20 book levels per side).
- **ATR breakout**: pair, ATR period, multiplier — fires on a large move in
  *either* direction.

Every rule can optionally pick a `notify.*` target — when the rule's
condition transitions from not-met to met, this integration calls
`notify.send_message` against it directly (edge-triggered: a condition that
stays true doesn't re-notify every check, only on the next off→on
transition). No notify target? The rule still tracks its state via its
binary sensor entity, so you can wire your own automation to it instead.

Existing rules are listed right there on the entry page, each with its own
**edit** and **delete** button — deleting a rule also removes its entity.
This is all handled by Home Assistant's own **Config Subentries** feature,
which is why this integration now requires **HA 2025.3.0+**.

How often rules are checked is configurable in Options → **Alert check
interval** (default 30s, floor 5s) — separate from, and much shorter than,
the balance/order poll interval, since alerting needs a tighter loop. Each
check fetches per pair only what that pair's rules actually need: the
ticker always, 1h candles only for candle-based indicators, the order book
only for OBI rules.

Balance/active-order polling interval is configurable in Options → **Account
data poll interval** (default 5 minutes) — kept conservative since Revolut X's
documented rate limits aren't generous (1000 requests/day for limit orders
specifically).

## Grid bots

⚠️ From the integration's entry page, an **"Add grid bot"** button lets you
define a live grid-trading bot for one pair — it places **REAL limit orders
using REAL funds** on Revolut X once armed. Each bot picks: pair, grid
levels per side (1-25), grid range (%), an **investment cap** (the hard
ceiling on quote currency it will ever commit to new buy orders), an
optional stop-loss price (0 disables it), a reconciliation interval
(default 30s), how many consecutive errors before it stops itself (default
5), whether to resume automatically after a Home Assistant restart (default
off — see below), and an optional `notify.*` target for stop-loss/kill-switch
alerts.

**Two-factor arming**: a bot only ever places an order if both this entry's
**Enable order placement (trading)** option (Options, off by default — same
toggle the 4 MCP trading tools use) and the bot's own switch are on. Turning
either off stops it.

**Execution model**: rests real limit buy orders below the current price at
each grid level; when Revolut X fills one, the bot places the mirror sell
one level up (and vice versa for sells), reconciling on the interval above.
This delegates price-crossing detection to Revolut X's own matching engine
rather than simulating it. `grid_backtest`/`grid_optimize` (below) share the
same grid-spacing math, so a backtest is a reasonable way to sanity-check
parameters before arming a bot with real funds.

**Stop ≠ flatten**: turning a bot's switch off cancels its own resting
orders (never any order it didn't place — see below) but leaves any
already-filled base-asset position exactly as-is. If you want to also close
that position, do it yourself via `place_order`/the Revolut X app.

**Safety design**, since an always-on bot placing orders on its own schedule
is a different risk category from the on-demand order-write tools:
- Every order gets a `client_order_id` namespaced to that specific bot; the
  bot only ever reads/cancels orders carrying its own namespace, and never
  calls `cancel_all_orders` (which has no symbol filter and would touch
  orders you placed manually too).
- After enough consecutive reconciliation failures (the "stop after N
  consecutive errors" setting), the bot stops itself, cancels nothing
  further (to avoid hammering a possibly-failing API), and notifies — a
  human has to investigate and re-arm it; there's no auto-recovery.
- If Home Assistant restarts while a bot is armed, it always refreshes its
  P&L/position from Revolut X immediately, but by default **stays stopped**
  until you turn it back on — resting orders are safe unattended on the
  exchange either way, so this default just avoids silently resuming
  autonomous order placement right after an uncontrolled restart you may
  not have noticed. Enable **Resume automatically after a Home Assistant
  restart** on a specific bot only if you've thought through that trade-off.
- Reconfiguring a bot's grid parameters is blocked while it's running — its
  live resting orders wouldn't match the new parameters otherwise. Stop it
  first.

v1 scope: no `split_investment`/`trailing_up` (the grid stays fixed once
armed — cancel and re-add the bot to change its range); partial fills are
treated as not-yet-filled.

## Dashboard

[`dashboard_example.yaml`](dashboard_example.yaml) is a bundled example
Lovelace dashboard covering balances, active orders, price-alert rule status,
and service health, using standard cards (tile, heading, grid) for everything
with a fixed, predictable entity ID. The two groups that grow over time —
per-currency balance sensors and per-alert-rule sensors, the latter named
after each rule's own title — are listed dynamically instead of hardcoded,
via the community [auto-entities](https://github.com/thomasloven/lovelace-auto-entities)
card (install via HACS → Frontend → search "auto-entities" → Download),
filtering on each entity's `revolut_x_category` attribute rather than
entity_id patterns. Balances are additionally rendered with the community
[bar-card](https://github.com/custom-cards/bar-card) (install via
HACS → Frontend → search "bar-card" → Download) instead of a plain tile —
each currency's bar fills to its "available" amount out of a max of
available + reserved, so the unfilled remainder of the bar is the reserved
amount, a proportional stacked view rather than a bare number. The
[Entities](#entities) section above explains what each entity means. Import
the dashboard via Settings → Dashboards → Add dashboard → New dashboard from
scratch, then its three-dot menu → Edit in YAML.

Grid-bot state (grid levels vs. current price, open positions, realized P&L)
isn't in this example yet — the new switch/P&L/status entities from
[Grid bots](#grid-bots) above can be added with standard tile cards the same
way the other sections are, but a proper grid-levels-vs-price visualization
is still an open question (see `ROADMAP.md` at the repo root).

## Grid backtest tools

`grid_backtest` and `grid_optimize` simulate a grid trading strategy against
historical candle data already available through this integration's `get_candles`
tool — no live orders are ever placed, and both are always available (no config
gate). `grid_backtest` runs one simulation for a given grid size/range/investment;
`grid_optimize` sweeps a range of grid sizes and ranges (capped at 200
combinations per call) and ranks the results by total P&L. Simulations run off
Home Assistant's event loop via `hass.async_add_executor_job`, since a full
`grid_optimize` sweep over tens of thousands of candles can take real CPU time.

## Knowledge-base tools

`list_kb_articles` and `search_kb` return short, originally-written summaries for
ten common Revolut X topics (fees, order types, why an order failed, locked
balances, etc.) — not a copy of Revolut's own help-center text. Each summary
points to Revolut's official help center for current, authoritative details.

## Local development

There's no Home Assistant instance in this repo to run the integration against
directly. Requires **Python 3.13+** (HA core itself has required it since
2025.2.0, and this integration's price-alert feature needs Config Subentries,
HA 2025.3.0+). To verify changes:

```bash
python -m py_compile custom_components/revolutx_mcp/*.py
pip install homeassistant cryptography aiohttp voluptuous
python -c "import custom_components.revolutx_mcp"  # from the repo root
python -m unittest discover -s tests -t .  # from the repo root — pure-function tests (grid-backtest, coordinators, alert indicators)
```

To actually run it, copy (or symlink) `custom_components/revolutx_mcp` into a real
or test Home Assistant instance's `custom_components/` directory, restart, and add
the integration.

## Not implemented (out of scope for this version)

- Live grid-bot execution (placing real orders continuously against a grid
  strategy, unsupervised) — `grid_backtest`/`grid_optimize` are stateless
  simulation only. See [ROADMAP.md](../../ROADMAP.md) for why this needs its
  own dedicated safety design before it's picked up.
- Sidebar admin panel, websocket API, update-checking.
