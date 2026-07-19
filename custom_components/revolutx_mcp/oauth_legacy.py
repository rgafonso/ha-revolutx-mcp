"""Minimal "legacy" OAuth 2.1 authorization-code + PKCE flow for MCP clients,
with just enough Dynamic Client Registration (RFC 7591) for clients that require
it (e.g. Claude, which errors with `registration_endpoint_missing` rather than
falling back when no client_id is pre-configured).

Discovery note: Home Assistant *core* permanently owns the bare
`/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource`
paths (`homeassistant/components/auth/login_flow.py`, part of the always-loaded
`auth` component) — no custom integration can register there. So this module's
metadata lives at paths scoped under our own issuer (`/api/revolutx_mcp`, per RFC
8414 §3.1's path-insertion convention), including the per-resource metadata (RFC
9728's equivalent convention) — which is deliberately kept under our own issuer
path too, rather than under the webhook's own `/api/webhook/<id>` path, since
reverse proxies in front of Home Assistant commonly special-case that literal
path pattern and would otherwise swallow it (see `webhook_resource_metadata_url`
below). `transport.py` points clients at the exact protected-resource-metadata
URL via the `resource_metadata` parameter on 401 responses (RFC 9728 §5.2: a
MUST-follow hint), so a spec-compliant client never needs to guess or hit the
HA-core-owned bare path.

DCR here is intentionally trivial: since redirect_uri is already not checked
against a pre-registered allowlist (see below) and PKCE is the real security
boundary, /register just mints and returns a fresh random client_id — no stored
client registry, nothing to look up later. /authorize and /token accept whatever
client_id shows up and only tie it into the issued code/token as an opaque label.

Security note: the consent step at /authorize requires an authenticated Home
Assistant session (`requires_auth = True`), which is the actual access-control
boundary: only someone who can already log into this Home Assistant instance can
mint a token. This mode exists for MCP clients that need a standard OAuth
handshake to paste a connector URL into; it is not a hardened multi-tenant
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

from aiohttp import ClientError, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    OAUTH_ACCESS_TOKEN_TTL,
    OAUTH_AUTH_CODE_TTL,
    OAUTH_CLIENT_ID,
    OAUTH_REFRESH_TOKEN_TTL,
)

_LOGGER = logging.getLogger(__name__)

# In-memory, single-process, one-shot — fine for authorization codes (5 min TTL).
_AUTH_CODES: dict[str, dict[str, Any]] = {}

ISSUER_PATH = "/api/revolutx_mcp"


def issuer_url(base: str) -> str:
    return f"{base.rstrip('/')}{ISSUER_PATH}"


def webhook_resource_metadata_url(base: str, webhook_id: str) -> str:
    # Deliberately does NOT reuse the `/api/webhook/<id>` path shape: some reverse
    # proxies in front of Home Assistant allow-list (or otherwise special-case)
    # exactly that path pattern for the real webhook, which then swallows this
    # discovery URL too since it happens to end the same way. Living under our own
    # issuer path instead sidesteps that class of collision; the JSON body's
    # `resource` field is what actually points at the real webhook URL.
    return f"{base.rstrip('/')}/.well-known/oauth-protected-resource{ISSUER_PATH}/{webhook_id}"


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


# In-memory, single-process — holds an in-flight authorize request while the
# browser is off delegating login to Home Assistant's own /auth/authorize.
# Short TTL (matches OAUTH_AUTH_CODE_TTL); popped (one-shot) at the callback.
_PENDING_REQUESTS: dict[str, dict[str, Any]] = {}


class AuthorizeView(HomeAssistantView):
    """GET /authorize — the entry point an OAuth client (e.g. Claude) redirects
    the user's browser to.

    This does not implement its own login/consent UI. `requires_auth = True`
    (the previous approach) assumed the browser already carried a Home
    Assistant session cookie, which it generally doesn't when opened fresh from
    an external client's OAuth flow — it just returned a bare 401. Instead this
    stashes the incoming request's params under a nonce and redirects to Home
    Assistant's own native `/auth/authorize` (frontend-rendered login page —
    the same mechanism HA's mobile app and documented OAuth clients use, see
    https://developers.home-assistant.io/docs/auth_api/), passing `client_id`
    == our own base URL and `redirect_uri` == AuthorizeCallbackView's URL,
    which indieauth.verify_redirect_uri accepts automatically since they share
    an origin — no pre-registration needed. AuthorizeCallbackView resumes once
    that login completes. Successfully logging into this Home Assistant
    instance *is* the consent (see module docstring's security note); there is
    no separate "Allow" click on top of that login screen.
    """

    url = f"{ISSUER_PATH}/authorize"
    name = "api:revolutx_mcp:authorize"
    requires_auth = False

    def __init__(self, base_url_fn) -> None:
        self._base_url_fn = base_url_fn

    async def get(self, request: web.Request) -> web.Response:
        params = request.query
        redirect_uri = params.get("redirect_uri", "")
        code_challenge = params.get("code_challenge", "")
        if not redirect_uri or not code_challenge:
            return web.Response(status=400, text="Missing redirect_uri or code_challenge")

        nonce = secrets.token_urlsafe(24)
        _PENDING_REQUESTS[nonce] = {
            "client_id": params.get("client_id", OAUTH_CLIENT_ID),
            "redirect_uri": redirect_uri,
            "state": params.get("state", ""),
            "code_challenge": code_challenge,
            "code_challenge_method": params.get("code_challenge_method", "S256"),
            "expires": time.time() + OAUTH_AUTH_CODE_TTL,
        }

        base = self._base_url_fn().rstrip("/")
        ha_authorize_url = f"{base}/auth/authorize?" + urlencode(
            {
                "response_type": "code",
                "client_id": base,
                "redirect_uri": f"{issuer_url(base)}/authorize/callback",
                "state": nonce,
            }
        )
        raise web.HTTPFound(ha_authorize_url)


class AuthorizeCallbackView(HomeAssistantView):
    """GET /authorize/callback — Home Assistant's own login page redirects here
    once the user has logged in, with an HA-issued authorization code. That
    code is exchanged at HA's own `/auth/token` (over loopback, to sidestep any
    reverse-proxy quirks on the external hostname — this is a pure
    server-to-server call) purely to confirm the login actually succeeded; the
    resulting HA token itself isn't needed afterwards. On success, issues our
    own authorization code for the original client and redirects to *its*
    redirect_uri, completing the flow AuthorizeView started."""

    url = f"{ISSUER_PATH}/authorize/callback"
    name = "api:revolutx_mcp:authorize-callback"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, base_url_fn) -> None:
        self._hass = hass
        self._base_url_fn = base_url_fn

    async def get(self, request: web.Request) -> web.Response:
        nonce = request.query.get("state", "")
        ha_code = request.query.get("code", "")
        pending = _PENDING_REQUESTS.pop(nonce, None)
        if pending is None or pending["expires"] < time.time():
            return web.Response(status=400, text="Expired or invalid authorization request")
        if not ha_code:
            return web.Response(status=400, text="Home Assistant login did not return a code")

        base = self._base_url_fn().rstrip("/")
        port = self._hass.http.server_port
        session = async_get_clientsession(self._hass)
        try:
            async with session.post(
                f"http://127.0.0.1:{port}/auth/token",
                data={"grant_type": "authorization_code", "code": ha_code, "client_id": base},
            ) as resp:
                if resp.status != 200:
                    return web.Response(status=401, text="Home Assistant login failed")
        except ClientError:
            _LOGGER.exception("Failed to reach Home Assistant's own token endpoint")
            return web.Response(status=502, text="Could not reach Home Assistant's own token endpoint")

        code = _issue_authorization_code(
            pending["client_id"],
            pending["redirect_uri"],
            pending["code_challenge"],
            pending["code_challenge_method"],
        )
        query = {"code": code}
        if pending["state"]:
            query["state"] = pending["state"]
        raise web.HTTPFound(f"{pending['redirect_uri']}?{urlencode(query)}")


class TokenView(HomeAssistantView):
    """POST /token — authorization_code and refresh_token grants."""

    url = f"{ISSUER_PATH}/token"
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


class RegisterView(HomeAssistantView):
    """POST /register — minimal RFC 7591 Dynamic Client Registration.

    No stored client registry: /authorize and /token already accept whatever
    client_id is presented (PKCE is the real security boundary), so this just
    mints a fresh opaque client_id and echoes back what the client asked for.
    """

    url = f"{ISSUER_PATH}/register"
    name = "api:revolutx_mcp:register"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        try:
            body: dict[str, Any] = await request.json()
        except ValueError:
            body = {}

        client_id = f"revolutx-mcp-{secrets.token_urlsafe(12)}"
        response = {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "redirect_uris": body.get("redirect_uris", []),
        }
        if "client_name" in body:
            response["client_name"] = body["client_name"]
        return web.json_response(response, status=201)


class AuthServerMetadataView(HomeAssistantView):
    """RFC 8414 authorization server metadata, scoped under our own issuer path
    so it doesn't collide with the one Home Assistant core always serves at the
    bare `/.well-known/oauth-authorization-server`."""

    url = f"/.well-known/oauth-authorization-server{ISSUER_PATH}"
    name = "api:revolutx_mcp:oauth-authorization-server"
    requires_auth = False

    def __init__(self, base_url_fn) -> None:
        self._base_url_fn = base_url_fn

    async def get(self, request: web.Request) -> web.Response:
        base = self._base_url_fn()
        return web.json_response(
            {
                "issuer": issuer_url(base),
                "authorization_endpoint": f"{issuer_url(base)}/authorize",
                "token_endpoint": f"{issuer_url(base)}/token",
                "registration_endpoint": f"{issuer_url(base)}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
        )


class ProtectedResourceMetadataView(HomeAssistantView):
    """RFC 9728 protected-resource metadata, scoped under our own issuer path
    (not the webhook's own `/api/webhook/<id>` path — see the comment in
    `webhook_resource_metadata_url` for why) so it doesn't collide with Home
    Assistant core's own bare `/.well-known/oauth-protected-resource`, or with
    any reverse-proxy rule scoped to the real webhook path. Registered once;
    `webhook_id` is a dynamic path segment, not tied to any single config entry."""

    url = "/.well-known/oauth-protected-resource" + ISSUER_PATH + "/{webhook_id}"
    name = "api:revolutx_mcp:oauth-protected-resource-webhook"
    requires_auth = False

    def __init__(self, base_url_fn) -> None:
        self._base_url_fn = base_url_fn

    async def get(self, request: web.Request, webhook_id: str) -> web.Response:
        base = self._base_url_fn()
        return web.json_response(
            {
                "resource": f"{base.rstrip('/')}/api/webhook/{webhook_id}",
                "authorization_servers": [issuer_url(base)],
            }
        )


def async_register_views(hass: HomeAssistant, signing_key: bytes, base_url_fn) -> None:
    """Register the legacy-OAuth HTTP views with Home Assistant's HTTP component."""
    hass.http.register_view(AuthorizeView(base_url_fn))
    hass.http.register_view(AuthorizeCallbackView(hass, base_url_fn))
    hass.http.register_view(TokenView(hass, signing_key))
    hass.http.register_view(RegisterView())
    hass.http.register_view(AuthServerMetadataView(base_url_fn))
    hass.http.register_view(ProtectedResourceMetadataView(base_url_fn))
