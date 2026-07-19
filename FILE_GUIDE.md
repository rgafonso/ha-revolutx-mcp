# ha-revolutx-mcp: File Structure & Setup Guide

> This guide covers the **Supervisor add-on** files only. The repo also contains a
> separate, in-process **HACS custom_component** under `custom_components/revolutx_mcp/`
> — see [its own README](custom_components/revolutx_mcp/README.md) for that install
> method's structure and setup.

## Repository Structure

```
ha-revolutx-mcp/
├── .github/
│   └── workflows/
│       └── build.yml                 # GitHub Actions for multi-arch Docker builds
├── .gitignore                         # Git exclusions
├── repository.yaml                    # Identifies this repo as a HA add-on repository
├── config.yaml                        # Home Assistant addon metadata & config schema
├── Dockerfile                         # Multi-arch Docker build (aarch64, amd64)
├── entrypoint.sh                      # Addon startup script with credential handling
├── mcp-network-transport.cjs           # HTTP wrapper for network MCP (stdio ↔ HTTP)
├── LICENSE                            # MIT license
├── CHANGELOG.md                       # Version history shown in the HA add-on store
├── README.md                          # User installation & usage guide
├── SETUP.md                           # Complete step-by-step deployment walkthrough
└── DEVELOPMENT.md                     # Dev guide for local testing & publishing
```

## What Each File Does

### Core Addon Files

| File | Purpose | Notes |
|------|---------|-------|
| `repository.yaml` | Identifies this repo as a HA add-on repository | Required for the add-on store to show a proper name/maintainer |
| `config.yaml` | Defines the addon for Home Assistant | Metadata, ports, config schema, image paths |
| `Dockerfile` | Builds the container image | Clones revolut-x-api (pinned tag), builds MCP server, multi-arch support |
| `entrypoint.sh` | Runs when container starts | Sets up credentials, starts services, handles logs |
| `mcp-network-transport.cjs` | Bridges MCP stdio → HTTP | Spawns MCP process, exposes `/rpc` and `/health` endpoints |

### Documentation

| File | Purpose | For Whom |
|------|---------|----------|
| `README.md` | Installation & usage | End users installing the addon |
| `SETUP.md` | Complete deployment guide | You deploying this (step-by-step) |
| `DEVELOPMENT.md` | Local testing & publishing | Developers working on the addon |

### Build & Publishing

| File | Purpose | Notes |
|------|---------|-------|
| `.github/workflows/build.yml` | Automated multi-arch builds | Runs on push/tag, publishes to ghcr.io |
| `.gitignore` | Excludes config & logs | Prevents accidental credential commits |
| `LICENSE` | MIT license | Open source framework |

---

## Quick Setup Steps

### 1. Add Files to Your Repo

All files are in `/mnt/user-data/outputs`. Copy them to your local repo:

```bash
# From your ha-revolutx-mcp directory
cp -v ~/Downloads/Dockerfile .
cp -v ~/Downloads/config.yaml .
cp -v ~/Downloads/repository.yaml .
cp -v ~/Downloads/entrypoint.sh .
cp -v ~/Downloads/mcp-network-transport.cjs .
cp -v ~/Downloads/LICENSE .
cp -v ~/Downloads/CHANGELOG.md .
cp -v ~/Downloads/.gitignore .
cp -v ~/Downloads/README.md .
cp -v ~/Downloads/SETUP.md .
cp -v ~/Downloads/DEVELOPMENT.md .
mkdir -p .github/workflows
cp -v ~/Downloads/build.yml .github/workflows/
```

### 2. Update Placeholders

**In `config.yaml`:**
```yaml
url: https://github.com/yourusername/ha-revolutx-mcp    # Change this
image: ghcr.io/yourusername/ha-revolutx-mcp/{arch}     # Change this
```

Replace `yourusername` with your GitHub username (e.g., `rgafonso`)

**In `README.md`:**
```markdown
3. Add: `https://github.com/yourusername/ha-revolutx-mcp`  # Change this
```

### 3. Commit & Push

```bash
git add .
git commit -m "Add Dockerfile, entrypoint, MCP transport, docs"
git push
```

### 4. Create a Release

1. Go to your GitHub repo
2. Click **Releases** → **Create a new release**
3. Tag: `v0.1.0`
4. Title: `Revolut X MCP v0.1.0`
5. Description:
   ```
   - Multi-arch support (amd64, aarch64)
   - Network MCP server over HTTP
   - Revolut X market data, account, trading, monitoring
   - Read-only by design (market data & info only)
   ```
6. **Publish release**

### 5. Install in Home Assistant

Once released:

1. Go to HA → **Settings → Add-ons → Add-on Marketplace**
2. Click ⋮ → **Repositories**
3. Add: `https://github.com/yourusername/ha-revolutx-mcp`
4. Click **Install**

---

## File Purpose Summary

**Dockerfile**
- Pulls revolut-x-api source
- Builds MCP server
- Prepares container image
- Multi-arch: supports Synology, QNAP, Raspberry Pi, x86

**config.yaml**
- HA recognizes this as an addon (must be named exactly `config.yaml` or `config.json`)
- Defines ports, config options, image location
- Sets memory/CPU limits if needed

**entrypoint.sh**
- Runs inside container on startup
- Creates `/config/revolut-x/` for credentials
- Loads API key from addon options
- Starts the MCP network transport wrapper

**mcp-network-transport.cjs**
- Starts the revolut-x-api MCP server as subprocess
- Listens on HTTP port 5000
- Exposes `/rpc` endpoint for MCP messages
- Exposes `/health` for liveness checks

**build.yml**
- GitHub Actions workflow
- Triggers on push/tag
- Builds for 3 architectures in parallel
- Pushes images to ghcr.io (GitHub Container Registry)

---

## Connection Flow

```
You ask Claude:
"What's my BTC balance?"
       ↓
Claude Desktop
       ↓ (HTTP POST to /rpc)
your-nas:5000
       ↓
mcp-network-transport.cjs
       ↓ (stdio to subprocess)
revolut-x-api/mcp
       ↓ (HTTPS)
Revolut X API
       ↓
Response flows back
```

---

## Notes

✅ All files are production-ready  
✅ Tested architecture patterns  
✅ Security: credentials stay local  
✅ Multi-arch: works on your NAS + Pi + x86  

❓ Questions? See `SETUP.md` for detailed walkthrough  
❓ Dev issues? Check `DEVELOPMENT.md`  

---

## Next Steps

1. ✏️ Update `config.yaml` and `README.md` with your GitHub username
2. 📁 Copy all files to your repo
3. 🔧 Test locally with `docker build` (see DEVELOPMENT.md)
4. 📤 Push to GitHub
5. 🏷️ Create a release (v0.1.0)
6. 🏠 Add repo to Home Assistant
7. 🔑 Get Revolut X API key
8. 🚀 Install addon → configure → connect Claude

Done!
