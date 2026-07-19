# Changelog

## 0.4.0

- Added optional order-placement tools (`place_order`, `replace_order`,
  `cancel_order`, `cancel_all_orders`), gated behind a new "Enable order
  placement (trading)" options-flow toggle (default off). This integration was
  strictly read-only through 0.3.x; giving an LLM unconditional order-placement
  access by default is not an acceptable default, but some users explicitly want
  it, so it's now available opt-in. When the toggle is off, the 4 tools are
  fully absent from `tools/list`, and calling one by name is rejected with the
  same error as a genuinely nonexistent tool (so a client can't distinguish
  "gated" from "doesn't exist"). Threaded end-to-end the same way `auth_mode`
  already is, from `entry.options` through `webhook.py`/`direct_server.py`/
  `transport.py` into `mcp_dispatch.py`. `RevolutXClient` gained the 4
  corresponding REST methods (`POST /orders`, `PUT /orders/{id}`,
  `DELETE /orders/{id}`, `DELETE /orders`); the place/replace response shape
  is normalized defensively in `mcp_dispatch.py` since the official OpenAPI
  spec's own example contradicts its own schema on whether `data` is an object
  or a one-element array.
- Added `grid_backtest` / `grid_optimize`: stateless historical simulation of a
  grid-trading strategy against existing `get_candles` data (`backtest.py`),
  ported from the upstream `revolut-x-api` repo's MCP server (which has long
  included this as a read-only, no-live-orders tool). No live orders, always
  enabled. Added a candle-windowing helper since our REST client caps
  `get_candles` at ~100 candles/call, unlike upstream's internally-paginated
  client — it loops sub-windows to assemble up to 50,000 candles per run. The
  core simulation runs via `hass.async_add_executor_job`: a `grid_optimize`
  sweep can run up to 200 full backtests over 50,000 candles of `Decimal`
  arithmetic, which can reach multi-second CPU time and would otherwise block
  Home Assistant's event loop.
- Added `list_kb_articles` / `search_kb`: static, originally-authored short
  summaries for 10 common Revolut X help topics (fees, order types, failed
  orders, locked balances, etc.), each pointing to Revolut's real help center
  for authoritative/current details. Not a port of upstream's bundled article
  text (copyrighted, and not reproducible from this research pass anyway).
- Added `tests/test_backtest.py` — the repo's first automated tests, scoped to
  the grid-backtest engine's pure math (the one piece of this release with no
  live system to sanity-check against). Everything else continues to be
  verified via `py_compile` + an import smoke test, per this project's
  established pattern; live confirmation against a real Revolut X account +
  Claude connection is still pending for the trading tools specifically.

## 0.3.2

- Fixed `legacy_oauth`'s `/authorize` endpoint returning a bare 401 for every
  real client, since it relied on `requires_auth = True` — which only accepts
  requests that already carry a Home Assistant session cookie, something a
  browser opened fresh from an external OAuth client's (e.g. Claude's) login
  redirect never has. Replaced the old "renders its own consent form, gated by
  a session cookie" approach with delegation to Home Assistant's own native
  `/auth/authorize` login page (the same mechanism HA's mobile app and
  documented OAuth clients use — no pre-registration needed, since
  `client_id`/`redirect_uri` just need matching origins per IndieAuth). A new
  `/authorize/callback` endpoint resumes the flow once that login completes:
  it exchanges the code HA hands back at HA's own `/auth/token` (over
  loopback, so it doesn't depend on the external hostname or reverse proxy) to
  confirm the login succeeded, then issues this integration's own code and
  redirects to the original client's `redirect_uri`. Verified end-to-end
  (DCR → authorize redirect → simulated HA login → callback → PKCE token
  exchange) against a full aiohttp test harness using Home Assistant's real
  view-dispatch code, and confirmed working live against Claude. Only
  `custom_components/revolutx_mcp`; the Supervisor add-on is unaffected.

## 0.3.1

- Fixed `legacy_oauth`'s protected-resource metadata URL (introduced in 0.3.0)
  404ing behind some reverse proxies: it previously ended in the literal
  `/api/webhook/<id>` path segment to mirror the webhook it describes, but
  proxies that specifically allow-list or otherwise special-case that exact
  path (a common pattern for hiding webhook IDs from internet scanners) ended
  up swallowing the discovery URL too, even though it's a completely different
  route. The metadata URL now lives under this integration's own issuer path
  (`/.well-known/oauth-protected-resource/api/revolutx_mcp/<webhook_id>`)
  instead — the 404 was reproduced live via `curl` against a real
  openresty-fronted custom domain; the fix itself is verified against an
  isolated aiohttp test harness using Home Assistant's real view-dispatch
  code, and confirmed working live (superseded by 0.3.2, which fixed a
  separate issue in the same flow and confirmed the whole thing end-to-end
  against Claude). The JSON body's `resource` field still correctly points at
  the real webhook URL. Only `custom_components/revolutx_mcp`;
  the Supervisor add-on is unaffected.

## 0.3.0

- Made `legacy_oauth` actually usable by OAuth-capable MCP clients (supersedes
  0.2.0's guidance to prefer `ha_auth`): live testing against Claude surfaced a
  second problem beyond the well-known collision — Claude's OAuth client
  errors with `registration_endpoint_missing` unless a Client ID is manually
  configured or the server supports Dynamic Client Registration (RFC 7591),
  and Home Assistant's native AS (the `ha_auth` target) doesn't support DCR at
  all (it's IndieAuth-only, confirmed via
  https://developers.home-assistant.io/docs/auth_api/ — client_id must be a
  URL matching the client's own redirect URI's origin, something a generic
  client like Claude doesn't implement). Fixed by:
  - Adding a minimal `/register` (DCR) endpoint to `oauth_legacy.py` — no
    persistent client registry, just mints a fresh opaque `client_id` per
    request, since PKCE (already required) is the real security boundary.
  - Moving this integration's own AS/protected-resource metadata to paths
    scoped under its own issuer and the specific webhook resource (RFC 8414
    §3.1 / RFC 9728's path-insertion conventions), instead of the bare
    `/.well-known/...` root Home Assistant core owns.
  - Pointing the webhook's 401 response at that exact metadata URL via the
    `resource_metadata` parameter in `WWW-Authenticate` (RFC 9728 §5.2, a
    MUST-follow hint), so a spec-compliant client reaches this integration's
    own OAuth server directly without ever touching the HA-core-owned path.
  `legacy_oauth` is now the recommended mode for OAuth-capable clients;
  `ha_auth` remains for reusing an existing Home Assistant login/token.

## 0.2.0

- Added a third auth mode, `ha_auth`, that validates bearer tokens against
  Home Assistant's own native auth system
  (`hass.auth.async_validate_access_token`) instead of this integration's own
  token store. Root cause: Home Assistant core permanently registers
  `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource`
  (`homeassistant/components/auth/login_flow.py`, part of the always-loaded
  `auth` component) pointing at its own `/auth/authorize` + `/auth/token`, on
  every installation — no custom integration, including this one's own
  `legacy_oauth` mode, can ever win that path. A client that does standard
  OAuth discovery will always find HA's native AS, so `ha_auth` is the only
  mode that reliably works with such clients; `legacy_oauth` is kept for
  clients that skip discovery and take hardcoded authorize/token URLs.

## 0.1.0 — first release

- **HACS custom_component** (`custom_components/revolutx_mcp`): runs in-process
  inside Home Assistant, no Docker/Node required. Read-only Revolut X tools
  (balances, orders, trades, order book, candles, tickers, public data) exposed
  over MCP via a Home Assistant webhook and/or a standalone direct-port server.
  Config flow validates credentials live; options flow covers auth mode
  (none / legacy OAuth), direct-server port, and external URL override.
  Verified end-to-end against a live Revolut X account through both the webhook
  (public internet, via a reverse-proxied domain) and the direct LAN URL, and
  through an actual Claude custom connector.
- **Supervisor add-on**: fixed into a working state — `config.yaml` (renamed
  from `addon.yaml`, which Supervisor never actually reads), `Dockerfile`,
  `entrypoint.sh`, and the network transport wrapper (renamed `.cjs` after a
  `"type": "module"` conflict with the upstream `revolut-x-api` package.json)
  now build and run correctly; verified locally with `docker build`/`docker run`
  against `/health` and a real MCP `/rpc` call.
- Multi-arch add-on builds: `aarch64`, `amd64`. `armv7` is not built — `sharp`,
  pulled in transitively by upstream `revolut-x-api`, has no prebuilt binary for
  `linuxmusl-armv7` and fails to compile from source there either (confirmed
  locally).
- CI (`build.yml`) publishes per-arch images at `ghcr.io/<repo>/<arch>:<version>`
  to match `config.yaml`'s image reference, using GitHub Actions majors that
  target Node 24 (clearing the prior Node 20 deprecation warning).
