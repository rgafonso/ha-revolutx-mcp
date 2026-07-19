# Revolut X Trading MCP Addon

Home Assistant addon that runs the Revolut X MCP server, exposing crypto trading, market data, and strategy tools to Claude Desktop and Claude Code.

## Features

- **Market Data**: Live prices, order books, candles, public trades
- **Account Management**: Check balances, view holdings
- **Trading**: Place/cancel orders (via Claude Code only, not from MCP)
- **Strategy Backtesting**: Test grid strategies with historical data
- **Price Monitoring**: Set alerts for technical indicators (RSI, MACD, Bollinger, etc.)
- **Network MCP**: Access via Claude Desktop custom connector over your home network

## Installation

### 1. Add the Repository to Home Assistant

1. Go to **Settings → Add-ons → Add-on Marketplace** (bottom right)
2. Click the three dots (⋮) → **Repositories**
3. Add: `https://github.com/rgafonso/ha-revolutx-mcp`
4. Click **Install**

### 2. Start the Addon

1. Click **Revolut X Trading MCP**
2. Toggle **Start on boot** (optional)
3. Click **Start**

### 3. Get Your Revolut X API Key

1. Go to [Revolut X](https://exchange.revolut.com) → **Profile → API Keys**
2. Click **Generate keypair** (save the public key)
3. Add the public key to your Revolut X account
4. Create a new API key → **copy it**

### 4. Configure the Addon

1. In Home Assistant, go to the addon **Configuration** tab
2. Paste your API key into the `api_key` field
3. Click **Save**
4. **Restart** the addon

### 5. Connect to Claude Desktop

1. Open Claude Desktop settings
2. Go to **Connectors** → **Add custom connector**
3. Fill in:
   - **Name**: `Revolut X`
   - **URL**: `http://your-nas-ip:5000`
   - **OAuth ID**: (leave blank for now)
   - **OAuth Secret**: (leave blank for now)
4. Click **Add**
5. In Claude, ask: **"Check my Revolut X balances"**

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
