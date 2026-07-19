# Complete Setup Guide: Revolut X MCP Addon

## Overview

You now have a Home Assistant addon that exposes the Revolut X MCP server over a network connection. This guide walks through:

1. **Prepare the repository** (GitHub)
2. **Build locally** (Docker)
3. **Install in Home Assistant** (your NAS)
4. **Connect Claude** (Desktop)

---

## Step 1: Prepare Your GitHub Repository

### 1a. Create the Repository

1. Go to https://github.com/new
2. Name it: `revolut-x-addon`
3. Make it **Public** (required for HA community later)
4. **Don't** initialize with README (you have one)
5. Click **Create repository**

### 1b. Push Code

```bash
cd /home/claude/revolut-x-addon

git remote add origin https://github.com/rgafonso/ha-revolutx-mcp.git
git branch -M main
git add .
git commit -m "Initial commit: Revolut X MCP addon"
git push -u origin main
```

### 1c. Update References

Before pushing, replace placeholders in these files:

**config.yaml:**
```yaml
url: https://github.com/rgafonso/ha-revolutx-mcp
image: ghcr.io/rgafonso/ha-revolutx-mcp/{arch}  # Change yourusername
```

**README.md:**
```markdown
3. Add: `https://github.com/rgafonso/ha-revolutx-mcp`  # Change yourusername
```

Then commit again:
```bash
git add config.yaml README.md
git commit -m "Update repository URLs"
git push
```

---

## Step 2: Build & Test Locally

### 2a. Docker Build

From the addon directory:

```bash
# Build for your architecture (example: ARM 64-bit for Synology/QNAP)
docker build -t revolut-x-mcp:dev .

# Run it locally
docker run -it \
  -p 5000:5000 \
  -e LOG_LEVEL=debug \
  -e api_key="" \
  revolut-x-mcp:dev
```

### 2b. Test the HTTP Endpoint

In another terminal:

```bash
# Health check
curl http://localhost:5000/health
# Expected: {"status":"ok"}

# Test MCP message (after you have API key configured)
curl -X POST http://localhost:5000/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}}}'
```

---

## Step 3: Install in Home Assistant

### 3a. Add Repository

1. Open **Home Assistant** on your NAS
2. Go to **Settings → Add-ons → Add-on Marketplace**
3. Click ⋮ (three dots) → **Repositories**
4. Paste: `https://github.com/rgafonso/ha-revolutx-mcp`
5. Click **Create** → **Install**

### 3b. Install the Addon

1. Refresh (F5) the add-ons marketplace
2. Search for **Revolut X**
3. Click it → **Install**

### 3c. Start the Addon

1. Click **Start**
2. Toggle **Start on boot** (recommended)
3. Check logs to confirm it's running:
   ```
   [INFO] Starting Revolut X MCP server on port 5000...
   [INFO] HTTP MCP bridge listening on port 5000
   ```

---

## Step 4: Get Your Revolut X API Key

1. Go to **https://exchange.revolut.com**
2. Profile → **API Keys**
3. Click **Generate Keypair**
4. Copy the **PUBLIC KEY**
5. Go back to API Keys → **Add Public Key** → paste
6. Click **Create API Key**
7. Copy the **API KEY** (64 characters)

---

## Step 5: Configure the Addon

1. In Home Assistant, go to the addon page
2. Click **Configuration** tab
3. Paste your API key into `api_key` field
4. Set `log_level` to `info` (or `debug` for troubleshooting)
5. Click **Save**
6. **Restart** the addon
7. Check logs confirm:
   ```
   [INFO] API key configured successfully
   [INFO] HTTP MCP bridge listening on port 5000
   ```

---

## Step 6: Connect Claude Desktop

### 6a. Find Your NAS IP

On your NAS or router, find the local IP (e.g., `192.168.1.50`)

### 6b. Add Custom Connector in Claude

1. **Claude Desktop Settings** → **Connectors**
2. Click **Add custom connector**
3. Fill in:
   - **Name**: `Revolut X`
   - **URL**: `http://192.168.1.50:5000`
   - **OAuth ID**: (leave empty for now)
   - **OAuth Secret**: (leave empty for now)
4. Click **Add**

### 6c. Test Connection

In Claude, ask:

> "Check my Revolut X balances"

or

> "Show me BTC-USD current price"

---

## Troubleshooting

### Claude can't reach the addon

**Error:** "Connection refused" or timeout

**Check:**
1. Addon is running (logs show no errors)
2. NAS IP is correct: `ping 192.168.1.50`
3. Port 5000 is open on NAS firewall
4. Your device is on the same network

**Test curl:**
```bash
curl http://192.168.1.50:5000/health
```

### API key not working

**Error:** "invalid API key" or no balances returned

**Check:**
1. API key is exactly correct (copy-paste from Revolut X)
2. Addon is restarted after saving
3. Check addon logs for auth errors

### MCP server crashes

**Error:** Process exit in logs

**Check:**
1. Node.js version in Dockerfile (should be 20+)
2. revolut-x-api build succeeded: `npm run build -w mcp`
3. `/app/mcp/dist/index.js` exists in container

**Debug:**
```bash
# Build with debug logs
docker build --build-arg LOG_LEVEL=debug -t revolut-x-mcp:dev .
```

---

## Next Steps

### Option A: Use It Now
- ✅ You have a working MCP addon on your NAS
- ✅ Connect it from any device on your network
- ✅ Ask Claude for market data, balances, strategy backtests

### Option B: Publish to Community
- Submit to **Home Assistant Community Store**
- Others can install with one click
- See DEVELOPMENT.md for submission steps

### Option C: Add Features
- Real-time price alerts (integrate with HA automations)
- WebSocket for bidirectional updates
- Telegram notifications (for non-Claude users)
- Dashboard card for HA UI

---

## Architecture Reference

```
Your Device (any on network)
    ↓ (HTTP POST to 192.168.1.50:5000)
Claude Desktop
    ↓
ha-mcp (custom connector routing)
    ↓
Home Assistant (on NAS)
    ↓
revolut-x-mcp (addon container)
    ├─ mcp-network-transport.cjs (HTTP wrapper)
    └─ revolut-x-api/mcp (MCP server)
        ↓
    Revolut X REST API (HTTPS)
```

---

## Security Notes

✅ **Secure:**
- Credentials stored locally on NAS
- No data sent to Anthropic
- MCP is read-only (no order execution via MCP)
- Each request is authenticated to Revolut X

⚠️ **Keep private:**
- Your NAS IP address
- Your API key
- Your balances/trades

---

## Support

- **Addon issues**: Check DEVELOPMENT.md
- **Revolut X API**: https://developer.revolut.com/docs/x-api
- **Home Assistant**: https://www.home-assistant.io/
- **MCP spec**: https://spec.modelcontextprotocol.io/
