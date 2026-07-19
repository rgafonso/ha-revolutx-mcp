# Development Guide

## Local Testing

### Prerequisites

- Docker and Docker Compose
- Home Assistant (local or remote)
- Node.js 20+

### Build Locally

```bash
# Clone this repository
git clone https://github.com/rgafonso/ha-revolutx-mcp.git
cd revolut-x-addon

# Build Docker image for your architecture
docker build -t revolut-x-mcp:dev .

# Run container locally
docker run -it \
  -p 5000:5000 \
  -e LOG_LEVEL=debug \
  -e api_key=your_api_key_here \
  -v $(pwd)/config:/config \
  revolut-x-mcp:dev
```

### Test HTTP Endpoint

```bash
# Health check
curl http://localhost:5000/health

# Send a test RPC message
curl -X POST http://localhost:5000/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

## Publishing to Home Assistant Community

1. **Create a GitHub repository** with this addon structure
2. **Add GitHub Actions workflow** (see `.github/workflows/`)
3. **Create releases** with version tags (v1.0.0, etc.)
4. **Submit to Home Assistant Community** at https://github.com/home-assistant/addons

## Multi-Architecture Builds

The `addon.yaml` specifies:
- `aarch64` (ARM 64-bit for NAS, Raspberry Pi 4+)
- `amd64` (Intel/AMD x86_64)
- `armv7` (ARM 32-bit for older RPi)

Use GitHub Actions with `build/qemu-action` for cross-platform builds:

```yaml
- uses: docker/setup-qemu-action@v3
- uses: docker/setup-buildx-action@v3
- uses: docker/build-push-action@v5
  with:
    platforms: linux/amd64,linux/arm64,linux/arm/v7
```

## Troubleshooting Build Issues

**Problem: MCP server fails to start**
- Check logs: addon Logs tab shows stderr
- Verify Node.js version matches requirements
- Ensure `/app/mcp/dist/index.js` exists after build

**Problem: HTTP timeout**
- Increase timeout in `mcp-network-transport.js` if Revolut API is slow
- Check MCP server is responding on subprocess

**Problem: Credential issues**
- Verify `REVOLUTX_CONFIG_DIR` points to `/config/revolut-x`
- Check file permissions: `chmod 600 /config/revolut-x/*`

## Next Steps

- [ ] Add WebSocket support for real-time updates
- [ ] Implement OAuth for secure credential handling
- [ ] Add price alert automations (integrate with HA)
- [ ] Publish to Home Assistant Community Store
