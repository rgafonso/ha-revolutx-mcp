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

AUTH_MODE_NONE = "none"
AUTH_MODE_LEGACY_OAUTH = "legacy_oauth"
AUTH_MODES = [AUTH_MODE_NONE, AUTH_MODE_LEGACY_OAUTH]

LOG_LEVELS = ["debug", "info", "warning", "error"]

DEFAULT_AUTH_MODE = AUTH_MODE_NONE
DEFAULT_DIRECT_SERVER_ENABLED = True
DEFAULT_DIRECT_SERVER_PORT = 8600
DEFAULT_LOG_LEVEL = "info"

REVX_API_BASE = "https://revx.revolut.com/api/1.0"

# OAuth (legacy) token lifetimes, in seconds.
OAUTH_ACCESS_TOKEN_TTL = 60 * 60
OAUTH_REFRESH_TOKEN_TTL = 60 * 60 * 24 * 30
OAUTH_AUTH_CODE_TTL = 5 * 60

# Hardcoded/pre-shared OAuth client — this integration does not implement dynamic
# client registration (RFC 7591 is only a SHOULD in the MCP auth spec, not a MUST).
OAUTH_CLIENT_ID = "revolutx-mcp"

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "Revolut X"
