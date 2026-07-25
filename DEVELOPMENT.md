# Development Guide

## Add-on File Reference

| File | Purpose | Notes |
|------|---------|-------|
| `repository.yaml` | Identifies this repo as a HA add-on repository | Required for the add-on store to show a proper name/maintainer |
| `config.yaml` | Defines the addon for Home Assistant | Metadata, ports, config schema, image paths |
| `Dockerfile` | Builds the container image | Clones revolut-x-api (pinned tag), builds MCP server, multi-arch support |
| `entrypoint.sh` | Runs when container starts | Sets up credentials, starts services, handles logs |
| `mcp-network-transport.cjs` | Bridges MCP stdio → HTTP | Spawns MCP process, exposes `/rpc` and `/health` endpoints |
| `.github/workflows/build.yml` | Automated multi-arch builds | Runs on push/tag, publishes to ghcr.io |

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

The `config.yaml` specifies:
- `aarch64` (ARM 64-bit for NAS, Raspberry Pi 4+)
- `amd64` (Intel/AMD x86_64)

`armv7` (32-bit ARM, older RPi) is intentionally not built: `sharp`, pulled in
transitively by the upstream `revolut-x-api` repo, has no prebuilt binary for
`linuxmusl-armv7` and fails to compile from source there either (verified locally
with `docker buildx build --platform linux/arm/v7`).

Use GitHub Actions with `build/qemu-action` for cross-platform builds:

```yaml
- uses: docker/setup-qemu-action@v4
- uses: docker/setup-buildx-action@v4
- uses: docker/build-push-action@v7
  with:
    platforms: linux/amd64,linux/arm64
```

## Troubleshooting Build Issues

**Problem: MCP server fails to start**
- Check logs: addon Logs tab shows stderr
- Verify Node.js version matches requirements
- Ensure `/app/mcp/dist/index.js` exists after build

**Problem: HTTP timeout**
- Increase timeout in `mcp-network-transport.cjs` if Revolut API is slow
- Check MCP server is responding on subprocess

**Problem: Credential issues**
- Verify `REVOLUTX_CONFIG_DIR` points to `/config/revolut-x`
- Check file permissions: `chmod 600 /config/revolut-x/*`

## Next Steps

- [ ] Add WebSocket support for real-time updates
- [ ] Implement OAuth for secure credential handling
- [ ] Add price alert automations (integrate with HA)
- [ ] Publish to Home Assistant Community Store
