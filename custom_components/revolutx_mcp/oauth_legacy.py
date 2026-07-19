"""Minimal "legacy" OAuth 2.1 authorization-code + PKCE flow for MCP clients.

This is deliberately small: a single hardcoded/pre-shared client_id (no dynamic
client registration — RFC 7591 is a SHOULD, not a MUST, in the MCP auth spec),
PKCE (S256) required on every exchange, and stateless HMAC-signed access/refresh
tokens (no database — they validate/expire on their own and survive restarts).

Security note: because there's no dynamic client registration, redirect_uri is not
checked against a pre-registered allowlist — only that it's echoed back consistently
between /authorize and /token. The consent step at /authorize requires an
authenticated Home Assistant session (`requires_auth = True`), which is the actual
access-control boundary: only someone who can already log into this Home Assistant
instance can mint a token. This mode exists for MCP clients that need a standard
OAuth handshake to paste a connector URL into; it is not a hardened multi-tenant
authorization server.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    OAUTH_ACCESS_TOKEN_TTL,
    OAUTH_AUTH_CODE_TTL,
    OAUTH_CLIENT_ID,
    OAUTH_REFRESH_TOKEN_TTL,
)

_LOGGER = logging.getLogger(__name__)

# In-memory, single-process, one-shot — fine for authorization codes (5 min TTL).
_AUTH_CODES: dict[str, dict[str, Any]] = {}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: bytes, signing_key: bytes) -> str:
    return _b64url_encode(hmac.new(signing_key, payload, hashlib.sha256).digest())


def _issue_token(kind: str, ttl: int, signing_key: bytes, client_id: str) -> str:
    claims = {
        "kind": kind,
        "cid": client_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
        "jti": secrets.token_hex(8),
    }
    payload = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    return f"{_b64url_encode(payload)}.{_sign(payload, signing_key)}"


def _decode_token(token: str, signing_key: bytes, expected_kind: str) -> dict[str, Any] | None:
    try:
        body, sig = token.split(".", 1)
        payload = _b64url_decode(body)
    except (ValueError, binascii.Error):
        return None
    if not hmac.compare_digest(_sign(payload, signing_key), sig):
        return None
    try:
        claims = json.loads(payload)
    except ValueError:
        return None
    if claims.get("kind") != expected_kind or claims.get("exp", 0) < time.time():
        return None
    return claims


def validate_access_token(token: str, signing_key: bytes) -> bool:
    """Return True if `token` is a currently-valid access token."""
    return _decode_token(token, signing_key, "access") is not None


def _verify_pkce(verifier: str, challenge: str, method: str) -> bool:
    if method != "S256":
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return hmac.compare_digest(_b64url_encode(digest), challenge)


def _issue_authorization_code(client_id: str, redirect_uri: str, code_challenge: str, code_challenge_method: str) -> str:
    code = secrets.token_urlsafe(32)
    _AUTH_CODES[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "expires": time.time() + OAUTH_AUTH_CODE_TTL,
    }
    return code


def _redeem_authorization_code(code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any] | None:
    entry = _AUTH_CODES.pop(code, None)  # one-shot
    if entry is None or entry["expires"] < time.time() or entry["redirect_uri"] != redirect_uri:
        return None
    if not _verify_pkce(code_verifier, entry["code_challenge"], entry["code_challenge_method"]):
        return None
    return entry


def issue_token_pair(signing_key: bytes, client_id: str) -> dict[str, Any]:
    return {
        "access_token": _issue_token("access", OAUTH_ACCESS_TOKEN_TTL, signing_key, client_id),
        "refresh_token": _issue_token("refresh", OAUTH_REFRESH_TOKEN_TTL, signing_key, client_id),
        "token_type": "Bearer",
        "expires_in": OAUTH_ACCESS_TOKEN_TTL,
    }


class AuthorizeView(HomeAssistantView):
    """GET renders a one-click consent confirmation, POST issues an auth code."""

    url = "/api/revolutx_mcp/authorize"
    name = "api:revolutx_mcp:authorize"
    requires_auth = True  # the HA login itself is the access-control boundary

    async def get(self, request: web.Request) -> web.Response:
        params = request.query
        html = f"""<!doctype html><html><body>
<h3>Allow this client to access Revolut X MCP tools?</h3>
<form method="post">
<input type="hidden" name="client_id" value="{params.get('client_id', '')}">
<input type="hidden" name="redirect_uri" value="{params.get('redirect_uri', '')}">
<input type="hidden" name="state" value="{params.get('state', '')}">
<input type="hidden" name="code_challenge" value="{params.get('code_challenge', '')}">
<input type="hidden" name="code_challenge_method" value="{params.get('code_challenge_method', 'S256')}">
<button type="submit">Allow</button>
</form></body></html>"""
        return web.Response(text=html, content_type="text/html")

    async def post(self, request: web.Request) -> web.Response:
        data = await request.post()
        redirect_uri = str(data.get("redirect_uri", ""))
        state = str(data.get("state", ""))
        code_challenge = str(data.get("code_challenge", ""))
        code_challenge_method = str(data.get("code_challenge_method", "S256"))
        client_id = str(data.get("client_id", OAUTH_CLIENT_ID))

        if not redirect_uri or not code_challenge:
            return web.Response(status=400, text="Missing redirect_uri or code_challenge")

        code = _issue_authorization_code(client_id, redirect_uri, code_challenge, code_challenge_method)
        query = {"code": code}
        if state:
            query["state"] = state
        raise web.HTTPFound(f"{redirect_uri}?{urlencode(query)}")


class TokenView(HomeAssistantView):
    """POST /token — authorization_code and refresh_token grants."""

    url = "/api/revolutx_mcp/token"
    name = "api:revolutx_mcp:token"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, signing_key: bytes) -> None:
        self._hass = hass
        self._signing_key = signing_key

    async def post(self, request: web.Request) -> web.Response:
        data = await request.post()
        grant_type = data.get("grant_type")

        if grant_type == "authorization_code":
            code = str(data.get("code", ""))
            verifier = str(data.get("code_verifier", ""))
            redirect_uri = str(data.get("redirect_uri", ""))
            entry = _redeem_authorization_code(code, verifier, redirect_uri)
            if entry is None:
                return web.json_response({"error": "invalid_grant"}, status=400)
            return web.json_response(issue_token_pair(self._signing_key, entry["client_id"]))

        if grant_type == "refresh_token":
            refresh_token = str(data.get("refresh_token", ""))
            claims = _decode_token(refresh_token, self._signing_key, "refresh")
            if claims is None:
                return web.json_response({"error": "invalid_grant"}, status=400)
            return web.json_response(
                {
                    "access_token": _issue_token(
                        "access", OAUTH_ACCESS_TOKEN_TTL, self._signing_key, claims["cid"]
                    ),
                    "token_type": "Bearer",
                    "expires_in": OAUTH_ACCESS_TOKEN_TTL,
                }
            )

        return web.json_response({"error": "unsupported_grant_type"}, status=400)


class AuthServerMetadataView(HomeAssistantView):
    """RFC 8414 authorization server metadata (MUST per the MCP auth spec)."""

    url = "/.well-known/oauth-authorization-server"
    name = "api:revolutx_mcp:oauth-authorization-server"
    requires_auth = False

    def __init__(self, base_url_fn) -> None:
        self._base_url_fn = base_url_fn

    async def get(self, request: web.Request) -> web.Response:
        base = self._base_url_fn()
        return web.json_response(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/api/revolutx_mcp/authorize",
                "token_endpoint": f"{base}/api/revolutx_mcp/token",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
        )


class ProtectedResourceMetadataView(HomeAssistantView):
    """RFC 9728 protected-resource metadata (MUST per the MCP auth spec)."""

    url = "/.well-known/oauth-protected-resource"
    name = "api:revolutx_mcp:oauth-protected-resource"
    requires_auth = False

    def __init__(self, base_url_fn) -> None:
        self._base_url_fn = base_url_fn

    async def get(self, request: web.Request) -> web.Response:
        base = self._base_url_fn()
        return web.json_response(
            {
                "resource": base,
                "authorization_servers": [base],
            }
        )


def async_register_views(hass: HomeAssistant, signing_key: bytes, base_url_fn) -> None:
    """Register the legacy-OAuth HTTP views with Home Assistant's HTTP component."""
    hass.http.register_view(AuthorizeView())
    hass.http.register_view(TokenView(hass, signing_key))
    hass.http.register_view(AuthServerMetadataView(base_url_fn))
    hass.http.register_view(ProtectedResourceMetadataView(base_url_fn))
