"""Shared HTTP-level MCP request handling, used by both the webhook transport and
the standalone direct-port server."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.core import HomeAssistant

from .const import AUTH_MODE_HA_AUTH, AUTH_MODE_LEGACY_OAUTH
from .mcp_dispatch import handle_message
from .oauth_legacy import validate_access_token
from .revolut_client import RevolutXClient

_LOGGER = logging.getLogger(__name__)


def _unauthorized(reason: str) -> web.Response:
    return web.json_response(
        {"error": "unauthorized", "error_description": reason},
        status=401,
        headers={"WWW-Authenticate": 'Bearer realm="revolutx_mcp"'},
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
) -> web.Response:
    """Validate auth (if configured) and dispatch an MCP JSON-RPC request body."""
    error = _check_auth(request, auth_mode, signing_key, hass)
    if error:
        return _unauthorized(error)

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

    response = await handle_message(client, message)
    if response is None:
        return web.Response(status=204)
    return web.json_response(response)
