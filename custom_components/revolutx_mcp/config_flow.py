"""Config flow (setup) and options flow (settings) for Revolut X MCP."""
from __future__ import annotations

import logging
import secrets
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import selector

from .const import (
    AUTH_MODES,
    CONF_API_KEY,
    CONF_AUTH_MODE,
    CONF_DIRECT_SERVER_ENABLED,
    CONF_DIRECT_SERVER_PORT,
    CONF_DIRECT_SERVER_SECRET,
    CONF_EXTERNAL_URL,
    CONF_LOG_LEVEL,
    CONF_OAUTH_SIGNING_KEY,
    CONF_PRIVATE_KEY,
    CONF_WEBHOOK_ID,
    DEFAULT_AUTH_MODE,
    DEFAULT_DIRECT_SERVER_ENABLED,
    DEFAULT_DIRECT_SERVER_PORT,
    DEFAULT_LOG_LEVEL,
    DOMAIN,
    LOG_LEVELS,
)
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient, load_private_key

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
                        CONF_DIRECT_SERVER_ENABLED: DEFAULT_DIRECT_SERVER_ENABLED,
                        CONF_DIRECT_SERVER_PORT: DEFAULT_DIRECT_SERVER_PORT,
                        CONF_EXTERNAL_URL: "",
                        CONF_LOG_LEVEL: DEFAULT_LOG_LEVEL,
                    },
                )

        return self.async_show_form(step_id="user", data_schema=_USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "RevolutXMCPOptionsFlow":
        return RevolutXMCPOptionsFlow()


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
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
