"""Shared HTTP-level MCP request handling, used by both the webhook transport and
the standalone direct-port server."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import AUTH_MODE_HA_AUTH, AUTH_MODE_LEGACY_OAUTH, DOMAIN
from .mcp_dispatch import handle_message
from .oauth_legacy import validate_access_token
from .revolut_client import RevolutXClient

_LOGGER = logging.getLogger(__name__)


def request_served_signal(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_request_served"


@dataclass
class RequestStats:
    """Push-updated counters behind the request-count/last-served sensors —
    mutated inline from the request handler, not on a poll cycle like
    RevolutXDataUpdateCoordinator. Recorded only for requests that pass auth
    and parse as a JSON-RPC object, so unauthenticated scanner/noise traffic
    against an open direct-server port doesn't inflate a counter meant to
    answer "is my MCP client actually talking to it"."""

    signal: str
    count: int = 0
    last_served: datetime | None = None

    def record(self, hass: HomeAssistant) -> None:
        self.count += 1
        self.last_served = dt_util.utcnow()
        async_dispatcher_send(hass, self.signal)


def _unauthorized(reason: str, resource_metadata_url: str | None = None) -> web.Response:
    challenge = 'Bearer realm="revolutx_mcp"'
    if resource_metadata_url:
        # RFC 9728 §5.2: a client MUST use this hint rather than guessing a
        # well-known path — the only reliable way to reach our own metadata,
        # since Home Assistant core owns the bare `.well-known` paths.
        challenge += f', resource_metadata="{resource_metadata_url}"'
    return web.json_response(
        {"error": "unauthorized", "error_description": reason},
        status=401,
        headers={"WWW-Authenticate": challenge},
    )


def _check_auth(
    request: web.Request, auth_mode: str, signing_key: bytes, hass: HomeAssistant
) -> str | None:
    """Return an error reason if the request fails auth for the configured mode, else None."""
    if auth_mode not in (AUTH_MODE_LEGACY_OAUTH, AUTH_MODE_HA_AUTH):
        return None

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return "Missing bearer token"
    token = header.removeprefix("Bearer ")

    if auth_mode == AUTH_MODE_LEGACY_OAUTH:
        if not validate_access_token(token, signing_key):
            return "Invalid or expired token"
        return None

    # AUTH_MODE_HA_AUTH: delegate entirely to Home Assistant's own auth system —
    # this validates tokens minted by HA core's native /auth/authorize + /auth/token
    # flow (or a user's Long-Lived Access Token), the same tokens issued via the
    # OAuth server HA core itself advertises at /.well-known/oauth-authorization-server.
    # That well-known path is owned by HA core (homeassistant/components/auth) on
    # every installation, regardless of what integrations are present, so it's the
    # only OAuth server a spec-compliant client will ever actually discover here.
    if hass.auth.async_validate_access_token(token) is None:
        return "Invalid or expired Home Assistant access token"
    return None


async def handle_mcp_http(
    request: web.Request,
    client: RevolutXClient,
    auth_mode: str,
    signing_key: bytes,
    hass: HomeAssistant,
    trading_enabled: bool = False,
    resource_metadata_url: str | None = None,
    stats: RequestStats | None = None,
) -> web.Response:
    """Validate auth (if configured) and dispatch an MCP JSON-RPC request body.

    `resource_metadata_url` is only meaningful for AUTH_MODE_LEGACY_OAUTH — for
    AUTH_MODE_HA_AUTH, the default (Home-Assistant-core-owned) bare `.well-known`
    path already points at the right authorization server, so callers should
    leave it unset in that mode.
    """
    error = _check_auth(request, auth_mode, signing_key, hass)
    if error:
        return _unauthorized(
            error, resource_metadata_url if auth_mode == AUTH_MODE_LEGACY_OAUTH else None
        )

    try:
        message: Any = await request.json()
    except ValueError:
        return web.json_response(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status=400,
        )

    if not isinstance(message, dict):
        return web.json_response(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
            status=400,
        )

    if stats is not None:
        stats.record(hass)

    response = await handle_message(client, message, trading_enabled)
    if response is None:
        return web.Response(status=204)
    return web.json_response(response)
