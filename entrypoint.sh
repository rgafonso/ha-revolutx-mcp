#!/bin/sh
set -e

# Configuration
CONFIG_DIR="/config/revolut-x"
API_KEY_FILE="$CONFIG_DIR/api.key"
LOG_LEVEL="${LOG_LEVEL:-info}"
PORT="${PORT:-5000}"

# Create config directory
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

# Function to save API key
save_api_key() {
  local key="$1"
  if [ -z "$key" ]; then
    echo "[ERROR] API key cannot be empty"
    return 1
  fi
  echo "$key" > "$API_KEY_FILE"
  chmod 600 "$API_KEY_FILE"
  echo "[INFO] API key saved to $API_KEY_FILE"
  return 0
}

# Check if API key is provided via environment (from Home Assistant addon options)
if [ -n "$api_key" ]; then
  echo "[INFO] Configuring API key from addon options..."
  if save_api_key "$api_key"; then
    echo "[INFO] API key configured successfully"
  fi
elif [ ! -f "$API_KEY_FILE" ]; then
  echo "[WARN] No API key configured yet"
  echo "[INFO] API key will be required before trading features are available"
fi

# Export for revolut-x-api
export REVOLUTX_CONFIG_DIR="$CONFIG_DIR"

# Start the MCP server with network transport wrapper
echo "[INFO] Starting Revolut X MCP server on port $PORT..."
cd /app

# Run the network-transport wrapper
node /app/mcp-network-transport.cjs

# Fallback if wrapper fails
exit 1
