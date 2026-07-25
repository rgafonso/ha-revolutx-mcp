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
    CONF_ALERT_CHECK_INTERVAL,
    CONF_API_KEY,
    CONF_AUTH_MODE,
    CONF_DIRECT_SERVER_ENABLED,
    CONF_DIRECT_SERVER_PORT,
    CONF_DIRECT_SERVER_SECRET,
    CONF_DIRECTION,
    CONF_EXTERNAL_URL,
    CONF_INDICATOR,
    CONF_LOG_LEVEL,
    CONF_LOOKBACK,
    CONF_NOTIFY_TARGET,
    CONF_OAUTH_SIGNING_KEY,
    CONF_PAIR,
    CONF_PERIOD,
    CONF_POLL_INTERVAL,
    CONF_PRIVATE_KEY,
    CONF_THRESHOLD,
    CONF_TRADING_ENABLED,
    CONF_WEBHOOK_ID,
    DEFAULT_ALERT_CHECK_INTERVAL_SECONDS,
    DEFAULT_AUTH_MODE,
    DEFAULT_DIRECT_SERVER_ENABLED,
    DEFAULT_DIRECT_SERVER_PORT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DEFAULT_PRICE_CHANGE_LOOKBACK,
    DEFAULT_PRICE_CHANGE_THRESHOLD,
    DEFAULT_RSI_PERIOD,
    DEFAULT_RSI_THRESHOLD,
    DEFAULT_TRADING_ENABLED,
    DIRECTION_ABOVE,
    DIRECTION_RISE,
    DIRECTIONS_ABOVE_BELOW,
    DIRECTIONS_RISE_FALL,
    DOMAIN,
    INDICATOR_PRICE,
    INDICATOR_PRICE_CHANGE,
    INDICATOR_RSI,
    LOG_LEVELS,
    POLL_INTERVAL_MAX_MINUTES,
    POLL_INTERVAL_MIN_MINUTES,
    SUBENTRY_TYPE_ALERT_RULE,
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
        return {SUBENTRY_TYPE_ALERT_RULE: AlertRuleSubentryFlow}


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


def _rule_title(indicator: str, data: dict[str, Any]) -> str:
    pair = str(data.get(CONF_PAIR, "")).upper()
    direction = data.get(CONF_DIRECTION, "")
    if indicator == INDICATOR_PRICE:
        return f"{pair} price {direction} {data[CONF_THRESHOLD]}"
    if indicator == INDICATOR_PRICE_CHANGE:
        return f"{pair} price {direction} {data[CONF_THRESHOLD]}% ({data[CONF_LOOKBACK]}c)"
    if indicator == INDICATOR_RSI:
        return f"{pair} RSI({data[CONF_PERIOD]}) {direction} {data[CONF_THRESHOLD]}"
    return pair


class AlertRuleSubentryFlow(ConfigSubentryFlow):
    """Add/edit one price-alert rule — see alert_coordinator.py for evaluation.

    Home Assistant shows one "Add alert rule" button (registered via
    RevolutXMCPConfigFlow.async_get_supported_subentry_types) that opens
    async_step_user's menu; each menu choice is its own indicator-specific
    form. The entry page's per-rule edit button drives async_step_reconfigure,
    which re-derives which form to show from the existing subentry's stored
    `indicator` field.

    Deliberately uses plain async_update_and_abort (no auto-reload) on
    reconfigure, not the newer async_update_reload_and_abort — this
    integration already has an entry-wide entry.add_update_listener
    (__init__.py) which already reloads on any subentry add/update/remove
    (HA core routes all three through _async_update_entry, which fires that
    listener); mixing both is deprecated since HA 2026.6.
    """

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="user", menu_options=[INDICATOR_PRICE, INDICATOR_PRICE_CHANGE, INDICATOR_RSI]
        )

    async def async_step_price(self, user_input: dict[str, Any] | None = None):
        return await self._show_or_save(INDICATOR_PRICE, _price_schema, user_input)

    async def async_step_price_change(self, user_input: dict[str, Any] | None = None):
        return await self._show_or_save(INDICATOR_PRICE_CHANGE, _price_change_schema, user_input)

    async def async_step_rsi(self, user_input: dict[str, Any] | None = None):
        return await self._show_or_save(INDICATOR_RSI, _rsi_schema, user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        indicator = self._get_reconfigure_subentry().data[CONF_INDICATOR]
        return await getattr(self, f"async_step_reconfigure_{indicator}")(user_input)

    async def async_step_reconfigure_price(self, user_input: dict[str, Any] | None = None):
        return await self._show_or_save(INDICATOR_PRICE, _price_schema, user_input, reconfigure=True)

    async def async_step_reconfigure_price_change(self, user_input: dict[str, Any] | None = None):
        return await self._show_or_save(
            INDICATOR_PRICE_CHANGE, _price_change_schema, user_input, reconfigure=True
        )

    async def async_step_reconfigure_rsi(self, user_input: dict[str, Any] | None = None):
        return await self._show_or_save(INDICATOR_RSI, _rsi_schema, user_input, reconfigure=True)

    async def _show_or_save(self, indicator, schema_fn, user_input, *, reconfigure: bool = False):
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
