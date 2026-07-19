# Changelog

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
