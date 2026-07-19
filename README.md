# Revolut X Trading MCP

Exposes Revolut X crypto exchange market data, account, and trading tools to
Claude Desktop and Claude Code via MCP.

---

## 🚀 Get Started

The recommended way to run this is the **HACS custom_component**. It installs into
Home Assistant through HACS, runs **in-process**, and works on **every** Home
Assistant installation type — Home Assistant OS, Supervised, Container, and Core.
No separate container, no access token to manage by default. It covers the
read-only tools only (market data, balances, orders/trades history — no order
placement; see its own README for the full scope and auth options).

**Add it to Home Assistant via HACS (the preferred install):**

[![Add Revolut X MCP to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=rgafonso&repository=ha-revolutx-mcp&category=integration)

**Quick start:**

1. Click the badge above, or in HACS open **Integrations → ⋮ → Custom repositories**, add `https://github.com/rgafonso/ha-revolutx-mcp` (category: **Integration**), then **Download**.
2. **Restart Home Assistant.**
3. Go to **Settings → Devices & Services → Add Integration**, search for **Revolut X MCP**, and paste your Revolut X API key and Ed25519 private key (PEM) — validated live against the Revolut X API before the entry is created.
4. Copy the connect URL from the entry's **Configure** screen — it's also printed in the Home Assistant log.
5. Paste that URL into your AI client — done.

Full details (auth modes, legacy OAuth, direct-port access): [custom_components/revolutx_mcp/README.md](custom_components/revolutx_mcp/README.md).

### 🏠 Home Assistant Add-on (alternative)

Prefer to run this as a Home Assistant **add-on** (Docker container) instead? It
has the fuller feature set described below (trading via Claude Code, strategy
backtesting, price alerts) but only runs on OS/Supervised installs, and needs its
own API key configured separately — it does not share credentials with the HACS
component.

**Add the repository to Home Assistant:**

[![Add Repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Frgafonso%2Fha-revolutx-mcp)

**Quick start:**

1. Click the badge above, or in Home Assistant go to **Settings → Add-ons → Add-on Marketplace → ⋮ → Repositories**, add `https://github.com/rgafonso/ha-revolutx-mcp`.
2. Install and **Start** the **Revolut X Trading MCP** add-on.
3. Get a Revolut X API key: [Revolut X](https://exchange.revolut.com) → Profile → API Keys → Generate keypair → add the public key to your account → create an API key.
4. Paste it into the addon's **Configuration** tab → Save → Restart.
5. In Claude Desktop: Settings → Connectors → Add custom connector → Name `Revolut X`, URL `http://your-nas-ip:5000` → Add.

The rest of this README documents the add-on in more detail.

---

## Features

- **Market Data**: Live prices, order books, candles, public trades
- **Account Management**: Check balances, view holdings
- **Trading**: Place/cancel orders (via Claude Code only, not from MCP)
- **Strategy Backtesting**: Test grid strategies with historical data
- **Price Monitoring**: Set alerts for technical indicators (RSI, MACD, Bollinger, etc.)
- **Network MCP**: Access via Claude Desktop custom connector over your home network

## Usage

Once connected, you can ask Claude to:

- "What are my crypto balances?"
- "Show me BTC-USD prices"
- "Get 4-hour candles for ETH-USD"
- "Backtest a grid strategy for BTC-USD"
- "Alert me if BTC > $100,000"

## Logs

View addon logs in Home Assistant:
- Go to **Settings → Add-ons → Revolut X Trading MCP**
- Click **Logs** tab
- Check `LOG_LEVEL` in Configuration if you need debug output

## Security

- ✅ Credentials stored locally on your NAS
- ✅ No data sent to Anthropic or any third party
- ✅ MCP server is read-only (no placing orders without explicit Claude Code action)
- ⚠️ Keep your NAS IP and API key private

## Troubleshooting

**"Connection refused" error**
- Ensure the addon is running: check **Logs** tab
- Confirm your NAS IP is accessible from your device
- Check firewall isn't blocking port 5000

**"API key invalid"**
- Verify the key in Configuration matches your Revolut X account
- Restart the addon

**Claude doesn't respond**
- Check addon logs for errors
- Verify the URL in Claude's connector matches your NAS IP:port

## Support

- [Revolut X API Docs](https://developer.revolut.com/docs/x-api)
- [revolut-x-api GitHub](https://github.com/revolut-engineering/revolut-x-api)

## License

MIT — see LICENSE
