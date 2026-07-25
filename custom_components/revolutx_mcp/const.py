"""Constants for the Revolut X MCP integration."""

DOMAIN = "revolutx_mcp"

CONF_API_KEY = "api_key"
CONF_PRIVATE_KEY = "private_key"
CONF_WEBHOOK_ID = "webhook_id"
CONF_OAUTH_SIGNING_KEY = "oauth_signing_key"
CONF_DIRECT_SERVER_SECRET = "direct_server_secret"

CONF_AUTH_MODE = "auth_mode"
CONF_DIRECT_SERVER_ENABLED = "direct_server_enabled"
CONF_DIRECT_SERVER_PORT = "direct_server_port"
CONF_EXTERNAL_URL = "external_url"
CONF_LOG_LEVEL = "log_level"
CONF_TRADING_ENABLED = "trading_enabled"
CONF_POLL_INTERVAL = "poll_interval"

AUTH_MODE_NONE = "none"
AUTH_MODE_LEGACY_OAUTH = "legacy_oauth"
AUTH_MODE_HA_AUTH = "ha_auth"
AUTH_MODES = [AUTH_MODE_NONE, AUTH_MODE_LEGACY_OAUTH, AUTH_MODE_HA_AUTH]

LOG_LEVELS = ["debug", "info", "warning", "error"]

DEFAULT_AUTH_MODE = AUTH_MODE_NONE
DEFAULT_DIRECT_SERVER_ENABLED = True
DEFAULT_DIRECT_SERVER_PORT = 8600
DEFAULT_LOG_LEVEL = "info"
DEFAULT_TRADING_ENABLED = False
# Revolut X's documented rate limit is 1000 requests/day for limit orders
# specifically; general endpoint limits aren't fully documented, so minutes
# rather than seconds is the safer default poll cadence for account entities.
DEFAULT_POLL_INTERVAL_MINUTES = 5
POLL_INTERVAL_MIN_MINUTES = 1
POLL_INTERVAL_MAX_MINUTES = 1440

REVX_API_BASE = "https://revx.revolut.com/api/1.0"

# OAuth (legacy) token lifetimes, in seconds.
OAUTH_ACCESS_TOKEN_TTL = 60 * 60
OAUTH_REFRESH_TOKEN_TTL = 60 * 60 * 24 * 30
OAUTH_AUTH_CODE_TTL = 5 * 60

# Hardcoded/pre-shared OAuth client — this integration does not implement dynamic
# client registration (RFC 7591 is only a SHOULD in the MCP auth spec, not a MUST).
OAUTH_CLIENT_ID = "revolutx-mcp"

MCP_PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "Revolut X"
