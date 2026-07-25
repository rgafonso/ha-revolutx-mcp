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

# Price-alert monitoring (subentries) — a separate, faster-cadence poll than
# the account-data coordinator above, mirroring the upstream revx CLI's own
# monitor default (10s) / floor (5s).
CONF_ALERT_CHECK_INTERVAL = "alert_check_interval"
DEFAULT_ALERT_CHECK_INTERVAL_SECONDS = 30
ALERT_CHECK_INTERVAL_MIN_SECONDS = 5
ALERT_CHECK_INTERVAL_MAX_SECONDS = 3600

SUBENTRY_TYPE_ALERT_RULE = "alert_rule"

# Live grid-bot execution (subentries) — places real orders. See grid_bot.py
# for the safety design (two-factor arming, order-namespace isolation,
# investment cap, consecutive-error kill switch, restart-resume policy).
SUBENTRY_TYPE_GRID_BOT = "grid_bot"

CONF_GRID_LEVELS = "grid_levels"  # per side, 1-25 — same bound as grid_backtest
CONF_RANGE_PCT = "range_pct"  # percent, e.g. 10 (engine divides by 100)
CONF_INVESTMENT = "investment"
CONF_STOP_LOSS_PRICE = "stop_loss_price"  # 0 = disabled, matches backtest convention
CONF_CHECK_INTERVAL = "check_interval"
CONF_MAX_CONSECUTIVE_ERRORS = "max_consecutive_errors"
CONF_AUTO_RESUME = "auto_resume"  # default False — see grid_bot.py restart policy

DEFAULT_GRID_BOT_CHECK_INTERVAL_SECONDS = 30
GRID_BOT_CHECK_INTERVAL_MIN_SECONDS = 10
GRID_BOT_CHECK_INTERVAL_MAX_SECONDS = 600
DEFAULT_MAX_CONSECUTIVE_ERRORS = 5
DEFAULT_AUTO_RESUME = False

# Namespaces every order a grid bot places, so it can identify (and only
# ever cancel) its own orders — never account-wide cancel_all_orders().
CLIENT_ORDER_ID_PREFIX = "revx-gb-"

DEFAULT_GRID_LEVELS = 5  # per side — matches grid_backtest's own default
DEFAULT_RANGE_PCT = 10  # percent — matches grid_backtest's own default

INDICATOR_PRICE = "price"
INDICATOR_PRICE_CHANGE = "price_change"
INDICATOR_RSI = "rsi"
INDICATOR_EMA_CROSS = "ema_cross"
INDICATOR_MACD = "macd"
INDICATOR_BOLLINGER = "bollinger"
INDICATOR_VOLUME_SPIKE = "volume_spike"
INDICATOR_SPREAD = "spread"
INDICATOR_OBI = "obi"
INDICATOR_ATR_BREAKOUT = "atr_breakout"
INDICATORS = [
    INDICATOR_PRICE,
    INDICATOR_PRICE_CHANGE,
    INDICATOR_RSI,
    INDICATOR_EMA_CROSS,
    INDICATOR_MACD,
    INDICATOR_BOLLINGER,
    INDICATOR_VOLUME_SPIKE,
    INDICATOR_SPREAD,
    INDICATOR_OBI,
    INDICATOR_ATR_BREAKOUT,
]

CONF_INDICATOR = "indicator"
CONF_PAIR = "pair"
CONF_DIRECTION = "direction"
CONF_THRESHOLD = "threshold"
CONF_PERIOD = "period"
CONF_LOOKBACK = "lookback"
CONF_NOTIFY_TARGET = "notify_target"
CONF_FAST_PERIOD = "fast_period"
CONF_SLOW_PERIOD = "slow_period"
CONF_SIGNAL_PERIOD = "signal_period"
CONF_STD_MULT = "std_mult"
CONF_BAND = "band"
CONF_MULTIPLIER = "multiplier"

DIRECTION_ABOVE = "above"
DIRECTION_BELOW = "below"
DIRECTIONS_ABOVE_BELOW = [DIRECTION_ABOVE, DIRECTION_BELOW]

DIRECTION_RISE = "rise"
DIRECTION_FALL = "fall"
DIRECTIONS_RISE_FALL = [DIRECTION_RISE, DIRECTION_FALL]

DIRECTION_BULLISH = "bullish"
DIRECTION_BEARISH = "bearish"
DIRECTIONS_BULLISH_BEARISH = [DIRECTION_BULLISH, DIRECTION_BEARISH]

BAND_UPPER = "upper"
BAND_LOWER = "lower"
BANDS = [BAND_UPPER, BAND_LOWER]

DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_THRESHOLD = 70
DEFAULT_PRICE_CHANGE_LOOKBACK = 24
DEFAULT_PRICE_CHANGE_THRESHOLD = 5
DEFAULT_EMA_FAST_PERIOD = 9
DEFAULT_EMA_SLOW_PERIOD = 21
DEFAULT_MACD_FAST_PERIOD = 12
DEFAULT_MACD_SLOW_PERIOD = 26
DEFAULT_MACD_SIGNAL_PERIOD = 9
DEFAULT_BOLLINGER_PERIOD = 20
DEFAULT_BOLLINGER_STD_MULT = 2
DEFAULT_VOLUME_SPIKE_PERIOD = 20
DEFAULT_VOLUME_SPIKE_MULTIPLIER = 2.0
DEFAULT_SPREAD_THRESHOLD = 0.5
DEFAULT_OBI_THRESHOLD = 0.3
DEFAULT_ATR_PERIOD = 14
DEFAULT_ATR_MULTIPLIER = 1.5

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
