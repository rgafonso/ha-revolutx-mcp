"""Config flow (setup) and options flow (settings) for Revolut X MCP."""
from __future__ import annotations

import logging
import secrets
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigSubentryFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import selector

from .const import (
    ALERT_CHECK_INTERVAL_MAX_SECONDS,
    ALERT_CHECK_INTERVAL_MIN_SECONDS,
    AUTH_MODES,
    BAND_UPPER,
    BANDS,
    CONF_ALERT_CHECK_INTERVAL,
    CONF_API_KEY,
    CONF_AUTH_MODE,
    CONF_AUTO_RESUME,
    CONF_BAND,
    CONF_CHECK_INTERVAL,
    CONF_DIRECT_SERVER_ENABLED,
    CONF_DIRECT_SERVER_PORT,
    CONF_DIRECT_SERVER_SECRET,
    CONF_DIRECTION,
    CONF_EXTERNAL_URL,
    CONF_FAST_PERIOD,
    CONF_GRID_LEVELS,
    CONF_INDICATOR,
    CONF_INVESTMENT,
    CONF_LOG_LEVEL,
    CONF_LOOKBACK,
    CONF_MAX_CONSECUTIVE_ERRORS,
    CONF_MULTIPLIER,
    CONF_NOTIFY_TARGET,
    CONF_OAUTH_SIGNING_KEY,
    CONF_PAIR,
    CONF_PERIOD,
    CONF_POLL_INTERVAL,
    CONF_PRIVATE_KEY,
    CONF_RANGE_PCT,
    CONF_SIGNAL_PERIOD,
    CONF_SLOW_PERIOD,
    CONF_STD_MULT,
    CONF_STOP_LOSS_PRICE,
    CONF_THRESHOLD,
    CONF_TRADING_ENABLED,
    CONF_WEBHOOK_ID,
    DEFAULT_ALERT_CHECK_INTERVAL_SECONDS,
    DEFAULT_ATR_MULTIPLIER,
    DEFAULT_ATR_PERIOD,
    DEFAULT_AUTH_MODE,
    DEFAULT_AUTO_RESUME,
    DEFAULT_BOLLINGER_PERIOD,
    DEFAULT_BOLLINGER_STD_MULT,
    DEFAULT_DIRECT_SERVER_ENABLED,
    DEFAULT_DIRECT_SERVER_PORT,
    DEFAULT_EMA_FAST_PERIOD,
    DEFAULT_EMA_SLOW_PERIOD,
    DEFAULT_GRID_BOT_CHECK_INTERVAL_SECONDS,
    DEFAULT_GRID_LEVELS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MACD_FAST_PERIOD,
    DEFAULT_MACD_SIGNAL_PERIOD,
    DEFAULT_MACD_SLOW_PERIOD,
    DEFAULT_MAX_CONSECUTIVE_ERRORS,
    DEFAULT_OBI_THRESHOLD,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DEFAULT_PRICE_CHANGE_LOOKBACK,
    DEFAULT_PRICE_CHANGE_THRESHOLD,
    DEFAULT_RANGE_PCT,
    DEFAULT_RSI_PERIOD,
    DEFAULT_RSI_THRESHOLD,
    DEFAULT_SPREAD_THRESHOLD,
    DEFAULT_TRADING_ENABLED,
    DEFAULT_VOLUME_SPIKE_MULTIPLIER,
    DEFAULT_VOLUME_SPIKE_PERIOD,
    DIRECTION_ABOVE,
    DIRECTION_BULLISH,
    DIRECTION_RISE,
    DIRECTIONS_ABOVE_BELOW,
    DIRECTIONS_BULLISH_BEARISH,
    DIRECTIONS_RISE_FALL,
    DOMAIN,
    GRID_BOT_CHECK_INTERVAL_MAX_SECONDS,
    GRID_BOT_CHECK_INTERVAL_MIN_SECONDS,
    INDICATOR_ATR_BREAKOUT,
    INDICATOR_BOLLINGER,
    INDICATOR_EMA_CROSS,
    INDICATOR_MACD,
    INDICATOR_OBI,
    INDICATOR_PRICE,
    INDICATOR_PRICE_CHANGE,
    INDICATOR_RSI,
    INDICATOR_SPREAD,
    INDICATOR_VOLUME_SPIKE,
    LOG_LEVELS,
    POLL_INTERVAL_MAX_MINUTES,
    POLL_INTERVAL_MIN_MINUTES,
    SUBENTRY_TYPE_ALERT_RULE,
    SUBENTRY_TYPE_GRID_BOT,
)
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient, load_private_key
from .urls import direct_connect_url, webhook_connect_url

_LOGGER = logging.getLogger(__name__)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_PRIVATE_KEY): selector({"text": {"multiline": True}}),
    }
)


async def _validate_credentials(hass, api_key: str, private_key_pem: str) -> None:
    """Raise ValueError on bad key format/credentials, else return None."""
    try:
        private_key = load_private_key(private_key_pem)
    except Exception as err:  # noqa: BLE001 - any parse failure is "invalid key"
        raise ValueError("invalid_private_key") from err

    session = aiohttp_client.async_get_clientsession(hass)
    client = RevolutXClient(session, api_key, private_key)
    try:
        await client.get_balances()
    except RevolutXAuthError as err:
        raise ValueError("invalid_auth") from err
    except RevolutXAPIError as err:
        raise ValueError("cannot_connect") from err


class RevolutXMCPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle initial setup: collect + validate Revolut X credentials."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_API_KEY], user_input[CONF_PRIVATE_KEY]
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                await self.async_set_unique_id(user_input[CONF_API_KEY])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Revolut X MCP",
                    data={
                        CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_PRIVATE_KEY: user_input[CONF_PRIVATE_KEY],
                        CONF_WEBHOOK_ID: secrets.token_hex(16),
                        CONF_OAUTH_SIGNING_KEY: secrets.token_hex(32),
                        CONF_DIRECT_SERVER_SECRET: f"private_{secrets.token_urlsafe(16)}",
                    },
                    options={
                        CONF_AUTH_MODE: DEFAULT_AUTH_MODE,
                        CONF_TRADING_ENABLED: DEFAULT_TRADING_ENABLED,
                        CONF_DIRECT_SERVER_ENABLED: DEFAULT_DIRECT_SERVER_ENABLED,
                        CONF_DIRECT_SERVER_PORT: DEFAULT_DIRECT_SERVER_PORT,
                        CONF_EXTERNAL_URL: "",
                        CONF_LOG_LEVEL: DEFAULT_LOG_LEVEL,
                        CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL_MINUTES,
                        CONF_ALERT_CHECK_INTERVAL: DEFAULT_ALERT_CHECK_INTERVAL_SECONDS,
                    },
                )

        return self.async_show_form(step_id="user", data_schema=_USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "RevolutXMCPOptionsFlow":
        return RevolutXMCPOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {
            SUBENTRY_TYPE_ALERT_RULE: AlertRuleSubentryFlow,
            SUBENTRY_TYPE_GRID_BOT: GridBotSubentryFlow,
        }


class RevolutXMCPOptionsFlow(OptionsFlow):
    """Options: auth mode, direct-server port/toggle, external URL override, log level.

    Does not set `self.config_entry` in __init__ — recent Home Assistant core
    versions made it a read-only property that the flow manager populates itself;
    assigning to it raises `AttributeError: property 'config_entry' has no setter`.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AUTH_MODE, default=current.get(CONF_AUTH_MODE, DEFAULT_AUTH_MODE)
                ): vol.In(AUTH_MODES),
                vol.Required(
                    CONF_TRADING_ENABLED,
                    default=current.get(CONF_TRADING_ENABLED, DEFAULT_TRADING_ENABLED),
                ): bool,
                vol.Required(
                    CONF_DIRECT_SERVER_ENABLED,
                    default=current.get(CONF_DIRECT_SERVER_ENABLED, DEFAULT_DIRECT_SERVER_ENABLED),
                ): bool,
                vol.Required(
                    CONF_DIRECT_SERVER_PORT,
                    default=current.get(CONF_DIRECT_SERVER_PORT, DEFAULT_DIRECT_SERVER_PORT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
                vol.Optional(
                    CONF_EXTERNAL_URL, default=current.get(CONF_EXTERNAL_URL, "")
                ): str,
                vol.Required(
                    CONF_LOG_LEVEL, default=current.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL)
                ): vol.In(LOG_LEVELS),
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=current.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_MINUTES),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=POLL_INTERVAL_MIN_MINUTES, max=POLL_INTERVAL_MAX_MINUTES),
                ),
                vol.Required(
                    CONF_ALERT_CHECK_INTERVAL,
                    default=current.get(CONF_ALERT_CHECK_INTERVAL, DEFAULT_ALERT_CHECK_INTERVAL_SECONDS),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=ALERT_CHECK_INTERVAL_MIN_SECONDS, max=ALERT_CHECK_INTERVAL_MAX_SECONDS),
                ),
            }
        )

        webhook_url = webhook_connect_url(self.hass, self.config_entry.data[CONF_WEBHOOK_ID])
        if current.get(CONF_DIRECT_SERVER_ENABLED, DEFAULT_DIRECT_SERVER_ENABLED):
            direct_url = direct_connect_url(
                self.hass,
                current.get(CONF_DIRECT_SERVER_PORT, DEFAULT_DIRECT_SERVER_PORT),
                self.config_entry.data[CONF_DIRECT_SERVER_SECRET],
            )
        else:
            direct_url = "disabled"

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"webhook_url": webhook_url, "direct_url": direct_url},
        )


def _notify_selector():
    return selector({"entity": {"domain": "notify"}})


def _price_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(CONF_DIRECTION, default=d.get(CONF_DIRECTION, DIRECTION_ABOVE)): vol.In(
                DIRECTIONS_ABOVE_BELOW
            ),
            vol.Required(CONF_THRESHOLD, default=d.get(CONF_THRESHOLD, vol.UNDEFINED)): vol.Coerce(float),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _price_change_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(CONF_DIRECTION, default=d.get(CONF_DIRECTION, DIRECTION_RISE)): vol.In(
                DIRECTIONS_RISE_FALL
            ),
            vol.Required(
                CONF_THRESHOLD, default=d.get(CONF_THRESHOLD, DEFAULT_PRICE_CHANGE_THRESHOLD)
            ): vol.Coerce(float),
            vol.Required(
                CONF_LOOKBACK, default=d.get(CONF_LOOKBACK, DEFAULT_PRICE_CHANGE_LOOKBACK)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _rsi_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(CONF_DIRECTION, default=d.get(CONF_DIRECTION, DIRECTION_ABOVE)): vol.In(
                DIRECTIONS_ABOVE_BELOW
            ),
            vol.Required(
                CONF_THRESHOLD, default=d.get(CONF_THRESHOLD, DEFAULT_RSI_THRESHOLD)
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
            vol.Required(CONF_PERIOD, default=d.get(CONF_PERIOD, DEFAULT_RSI_PERIOD)): vol.All(
                vol.Coerce(int), vol.Range(min=2, max=200)
            ),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _ema_cross_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(
                CONF_DIRECTION, default=d.get(CONF_DIRECTION, DIRECTION_BULLISH)
            ): vol.In(DIRECTIONS_BULLISH_BEARISH),
            vol.Required(
                CONF_FAST_PERIOD, default=d.get(CONF_FAST_PERIOD, DEFAULT_EMA_FAST_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Required(
                CONF_SLOW_PERIOD, default=d.get(CONF_SLOW_PERIOD, DEFAULT_EMA_SLOW_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _macd_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(
                CONF_DIRECTION, default=d.get(CONF_DIRECTION, DIRECTION_BULLISH)
            ): vol.In(DIRECTIONS_BULLISH_BEARISH),
            vol.Required(
                CONF_FAST_PERIOD, default=d.get(CONF_FAST_PERIOD, DEFAULT_MACD_FAST_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Required(
                CONF_SLOW_PERIOD, default=d.get(CONF_SLOW_PERIOD, DEFAULT_MACD_SLOW_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Required(
                CONF_SIGNAL_PERIOD, default=d.get(CONF_SIGNAL_PERIOD, DEFAULT_MACD_SIGNAL_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _bollinger_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(CONF_BAND, default=d.get(CONF_BAND, BAND_UPPER)): vol.In(BANDS),
            vol.Required(
                CONF_PERIOD, default=d.get(CONF_PERIOD, DEFAULT_BOLLINGER_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Required(
                CONF_STD_MULT, default=d.get(CONF_STD_MULT, DEFAULT_BOLLINGER_STD_MULT)
            ): vol.Coerce(float),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _volume_spike_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(
                CONF_PERIOD, default=d.get(CONF_PERIOD, DEFAULT_VOLUME_SPIKE_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Required(
                CONF_MULTIPLIER, default=d.get(CONF_MULTIPLIER, DEFAULT_VOLUME_SPIKE_MULTIPLIER)
            ): vol.Coerce(float),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _spread_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(CONF_DIRECTION, default=d.get(CONF_DIRECTION, DIRECTION_ABOVE)): vol.In(
                DIRECTIONS_ABOVE_BELOW
            ),
            vol.Required(
                CONF_THRESHOLD, default=d.get(CONF_THRESHOLD, DEFAULT_SPREAD_THRESHOLD)
            ): vol.Coerce(float),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _obi_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(CONF_DIRECTION, default=d.get(CONF_DIRECTION, DIRECTION_ABOVE)): vol.In(
                DIRECTIONS_ABOVE_BELOW
            ),
            vol.Required(
                CONF_THRESHOLD, default=d.get(CONF_THRESHOLD, DEFAULT_OBI_THRESHOLD)
            ): vol.All(vol.Coerce(float), vol.Range(min=-1, max=1)),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _atr_breakout_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(
                CONF_PERIOD, default=d.get(CONF_PERIOD, DEFAULT_ATR_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=500)),
            vol.Required(
                CONF_MULTIPLIER, default=d.get(CONF_MULTIPLIER, DEFAULT_ATR_MULTIPLIER)
            ): vol.Coerce(float),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


def _rule_title(indicator: str, data: dict[str, Any]) -> str:
    pair = str(data.get(CONF_PAIR, "")).upper()
    direction = data.get(CONF_DIRECTION, "")
    if indicator == INDICATOR_PRICE:
        return f"{pair} price {direction} {data[CONF_THRESHOLD]}"
    if indicator == INDICATOR_PRICE_CHANGE:
        return f"{pair} price {direction} {data[CONF_THRESHOLD]}% ({data[CONF_LOOKBACK]}c)"
    if indicator == INDICATOR_RSI:
        return f"{pair} RSI({data[CONF_PERIOD]}) {direction} {data[CONF_THRESHOLD]}"
    if indicator == INDICATOR_EMA_CROSS:
        return f"{pair} EMA({data[CONF_FAST_PERIOD]}/{data[CONF_SLOW_PERIOD]}) {direction}"
    if indicator == INDICATOR_MACD:
        return f"{pair} MACD({data[CONF_FAST_PERIOD]},{data[CONF_SLOW_PERIOD]},{data[CONF_SIGNAL_PERIOD]}) {direction}"
    if indicator == INDICATOR_BOLLINGER:
        return f"{pair} Bollinger {data[CONF_BAND]} band ({data[CONF_PERIOD]},{data[CONF_STD_MULT]})"
    if indicator == INDICATOR_VOLUME_SPIKE:
        return f"{pair} volume spike {data[CONF_MULTIPLIER]}x ({data[CONF_PERIOD]}c)"
    if indicator == INDICATOR_SPREAD:
        return f"{pair} spread {direction} {data[CONF_THRESHOLD]}%"
    if indicator == INDICATOR_OBI:
        return f"{pair} OBI {direction} {data[CONF_THRESHOLD]}"
    if indicator == INDICATOR_ATR_BREAKOUT:
        return f"{pair} ATR({data[CONF_PERIOD]}) breakout {data[CONF_MULTIPLIER]}x"
    return pair


# One schema builder per indicator type; keys double as the menu order shown
# in the "Add alert rule" UI.
_INDICATOR_SCHEMAS = {
    INDICATOR_PRICE: _price_schema,
    INDICATOR_PRICE_CHANGE: _price_change_schema,
    INDICATOR_RSI: _rsi_schema,
    INDICATOR_EMA_CROSS: _ema_cross_schema,
    INDICATOR_MACD: _macd_schema,
    INDICATOR_BOLLINGER: _bollinger_schema,
    INDICATOR_VOLUME_SPIKE: _volume_spike_schema,
    INDICATOR_SPREAD: _spread_schema,
    INDICATOR_OBI: _obi_schema,
    INDICATOR_ATR_BREAKOUT: _atr_breakout_schema,
}


class AlertRuleSubentryFlow(ConfigSubentryFlow):
    """Add/edit one price-alert rule — see alert_coordinator.py for evaluation.

    Home Assistant shows one "Add alert rule" button (registered via
    RevolutXMCPConfigFlow.async_get_supported_subentry_types) that opens
    async_step_user's menu; each menu choice is its own indicator-specific
    form. The entry page's per-rule edit button drives async_step_reconfigure,
    which re-derives which form to show from the existing subentry's stored
    `indicator` field. The per-indicator `async_step_*` methods are generated
    below the class body — HA's flow framework resolves a step strictly by
    `async_step_<step_id>` method name, so each menu option/step id needs a
    real method to land on.

    Deliberately uses plain async_update_and_abort (no auto-reload) on
    reconfigure, not the newer async_update_reload_and_abort — this
    integration already has an entry-wide entry.add_update_listener
    (__init__.py) which already reloads on any subentry add/update/remove
    (HA core routes all three through _async_update_entry, which fires that
    listener); mixing both is deprecated since HA 2026.6.
    """

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(step_id="user", menu_options=list(_INDICATOR_SCHEMAS))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        indicator = self._get_reconfigure_subentry().data[CONF_INDICATOR]
        return await getattr(self, f"async_step_reconfigure_{indicator}")(user_input)

    async def _show_or_save(self, indicator, user_input, *, reconfigure: bool = False):
        schema_fn = _INDICATOR_SCHEMAS[indicator]
        if user_input is not None:
            data = dict(user_input)
            data[CONF_PAIR] = str(data[CONF_PAIR]).strip().upper()
            data[CONF_INDICATOR] = indicator
            title = _rule_title(indicator, data)
            if reconfigure:
                return self.async_update_and_abort(
                    self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
                )
            return self.async_create_entry(title=title, data=data)

        defaults = self._get_reconfigure_subentry().data if reconfigure else None
        step_id = f"reconfigure_{indicator}" if reconfigure else indicator
        return self.async_show_form(step_id=step_id, data_schema=schema_fn(defaults))


def _make_step(indicator: str, reconfigure: bool):
    async def _step(self: AlertRuleSubentryFlow, user_input: dict[str, Any] | None = None):
        return await self._show_or_save(indicator, user_input, reconfigure=reconfigure)

    return _step


for _indicator in _INDICATOR_SCHEMAS:
    setattr(AlertRuleSubentryFlow, f"async_step_{_indicator}", _make_step(_indicator, False))
    setattr(
        AlertRuleSubentryFlow,
        f"async_step_reconfigure_{_indicator}",
        _make_step(_indicator, True),
    )


def _grid_bot_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIR, default=d.get(CONF_PAIR, "")): str,
            vol.Required(
                CONF_GRID_LEVELS, default=d.get(CONF_GRID_LEVELS, DEFAULT_GRID_LEVELS)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=25)),
            vol.Required(
                CONF_RANGE_PCT, default=d.get(CONF_RANGE_PCT, DEFAULT_RANGE_PCT)
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=95)),
            vol.Required(CONF_INVESTMENT, default=d.get(CONF_INVESTMENT, vol.UNDEFINED)): vol.All(
                vol.Coerce(float), vol.Range(min=0, min_included=False)
            ),
            vol.Optional(
                CONF_STOP_LOSS_PRICE, default=d.get(CONF_STOP_LOSS_PRICE, 0)
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Required(
                CONF_CHECK_INTERVAL,
                default=d.get(CONF_CHECK_INTERVAL, DEFAULT_GRID_BOT_CHECK_INTERVAL_SECONDS),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=GRID_BOT_CHECK_INTERVAL_MIN_SECONDS, max=GRID_BOT_CHECK_INTERVAL_MAX_SECONDS),
            ),
            vol.Required(
                CONF_MAX_CONSECUTIVE_ERRORS,
                default=d.get(CONF_MAX_CONSECUTIVE_ERRORS, DEFAULT_MAX_CONSECUTIVE_ERRORS),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
            vol.Optional(
                CONF_AUTO_RESUME, default=d.get(CONF_AUTO_RESUME, DEFAULT_AUTO_RESUME)
            ): bool,
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, vol.UNDEFINED)
            ): _notify_selector(),
        }
    )


class GridBotSubentryFlow(ConfigSubentryFlow):
    """Add/edit one live grid-trading bot — see grid_bot.py for execution and
    the safety design (two-factor arming, order-namespace isolation,
    investment cap, consecutive-error kill switch, restart-resume policy).

    Single schema (not a per-indicator menu like AlertRuleSubentryFlow) since
    there's only one kind of grid bot. Same plain async_update_and_abort
    pattern as AlertRuleSubentryFlow and for the same reason — see its
    docstring.

    Reconfigure is blocked while the bot is running: changing grid
    parameters out from under live resting orders is unsafe, so the runtime
    engine's is_running (hass.data[DOMAIN][entry_id].grid_bot_engines) is
    checked before showing the form, and the user must stop the bot first.
    """

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            data = dict(user_input)
            data[CONF_PAIR] = str(data[CONF_PAIR]).strip().upper()
            return self.async_create_entry(title=f"{data[CONF_PAIR]} grid bot", data=data)
        return self.async_show_form(step_id="user", data_schema=_grid_bot_schema())

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        subentry = self._get_reconfigure_subentry()
        if self._engine_running(subentry.subentry_id):
            return self.async_abort(reason="bot_running")

        if user_input is not None:
            data = dict(user_input)
            data[CONF_PAIR] = str(data[CONF_PAIR]).strip().upper()
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=f"{data[CONF_PAIR]} grid bot", data=data
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_grid_bot_schema(subentry.data)
        )

    def _engine_running(self, subentry_id: str) -> bool:
        runtime = self.hass.data.get(DOMAIN, {}).get(self._get_entry().entry_id)
        if runtime is None:
            return False
        engine = runtime.grid_bot_engines.get(subentry_id)
        return bool(engine and engine.is_running)
