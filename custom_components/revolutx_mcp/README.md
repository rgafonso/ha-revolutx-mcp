# Revolut X MCP (Home Assistant custom_component)

An in-process Home Assistant integration that exposes read-only Revolut X market
data and account tools over MCP (Model Context Protocol) — no separate container,
no Node.js, works on Home Assistant OS, Supervised, Container, and Core.

This is a separate distribution method from this repo's Supervisor add-on
(`config.yaml`/`Dockerfile` at the repo root) — install one or the other, not both,
for a given Revolut X account.

## What it does

- Runs the Revolut X MCP tool logic (balances, orders, trades, order book, candles,
  tickers, public market data — 14 read-only tools total) directly inside Home
  Assistant's own event loop, signing requests to the Revolut X API with the
  Ed25519 private key you provide.
- Never places or cancels orders — `POST /orders` and `DELETE /orders/{id}` are not
  implemented, matching this project's existing read-only stance.
- Exposes those tools two ways: through a Home Assistant **webhook** (reachable via
  Nabu Casa remote access or any reverse proxy already pointed at your HA
  instance), and optionally through a **standalone port** for direct LAN access.

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
- **ha_auth** (recommended if you want per-client OAuth login instead of a secret
  URL): tokens are validated against Home Assistant's own native auth system
  (`hass.auth.async_validate_access_token`) — the same tokens issued by HA core's
  own `/auth/authorize` + `/auth/token` flow, or a Long-Lived Access Token from
  your HA user profile. This is the mode to use with OAuth-capable MCP clients,
  because of the collision described below.
- **legacy_oauth**: this integration's *own* OAuth 2.1 Authorization Code + PKCE
  server (`/api/revolutx_mcp/authorize`, `/api/revolutx_mcp/token`). Kept for
  completeness, but **in practice it's unreachable by any client that does
  standard OAuth discovery**: Home Assistant *core itself* permanently registers
  `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource`
  (`homeassistant/components/auth/login_flow.py`, part of the always-loaded `auth`
  component) pointing at its own `/auth/authorize` + `/auth/token` — on every HA
  installation, regardless of what integrations are present. No custom integration
  can win that path. A client that discovers first and authenticates second will
  end up authenticating against HA's native AS, not this one, and this webhook
  won't accept HA-native tokens in `legacy_oauth` mode (only `ha_auth` mode does).
  Use `legacy_oauth` only if you know your client skips discovery and lets you
  hardcode the authorize/token URLs directly. See `oauth_legacy.py` for the full
  design notes.

## Connect a client

- **Webhook URL**: shown at the top of the integration's **Configure** screen, in
  a Home Assistant notification when the server starts, and in the HA log.
  Format: `<your-ha-url>/api/webhook/<webhook_id>`.
- **Direct URL** (if enabled): `http://<ha-host>:<port>/<random-path>`, shown in
  the same three places.

Paste either URL into your MCP client (e.g. a Claude Desktop custom connector).

## Local development

There's no Home Assistant instance in this repo to run the integration against
directly. To verify changes:

```bash
python -m py_compile custom_components/revolutx_mcp/*.py
pip install homeassistant cryptography aiohttp voluptuous
python -c "import custom_components.revolutx_mcp"  # from the repo root
```

To actually run it, copy (or symlink) `custom_components/revolutx_mcp` into a real
or test Home Assistant instance's `custom_components/` directory, restart, and add
the integration.

## Not implemented (out of scope for this version)

- Strategy backtesting and price-alert monitoring (present in the add-on's README
  as long-term goals; stateful features, left for a follow-up).
- Sidebar admin panel, websocket API, update-checking, `ha_auth` mode.
- Dynamic OAuth client registration (RFC 7591) — the legacy OAuth client_id is
  fixed (`revolutx-mcp`).
