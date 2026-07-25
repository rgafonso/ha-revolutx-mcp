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
directly. To verify changes:

```bash
python -m py_compile custom_components/revolutx_mcp/*.py
pip install homeassistant cryptography aiohttp voluptuous
python -c "import custom_components.revolutx_mcp"  # from the repo root
python -m unittest discover -s tests -t .  # from the repo root — grid-backtest math only
```

To actually run it, copy (or symlink) `custom_components/revolutx_mcp` into a real
or test Home Assistant instance's `custom_components/` directory, restart, and add
the integration.

## Not implemented (out of scope for this version)

- Price-alert monitoring and other stateful/long-running background features
  (grid-strategy backtesting is implemented as a stateless simulation tool;
  ongoing monitoring would need persistent background state this integration
  doesn't have). See [ROADMAP.md](../../ROADMAP.md) for the intended direction.
- Sidebar admin panel, websocket API, update-checking.
