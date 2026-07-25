"""Async client for the Revolut X REST API.

Auth: three custom headers (X-Revx-API-Key, X-Revx-Timestamp, X-Revx-Signature),
where the signature is a base64-encoded Ed25519 signature over
`timestamp + METHOD + path + query + body` (no separators, body minified JSON).
See: https://github.com/revolut-engineering/revolut-x-api (revolut-x-api-for-llm.md).

Covers the full read-only surface plus order placement/replacement/cancellation.
The write methods are only reachable from MCP tools gated behind this
integration's own `trading_enabled` config option (see mcp_dispatch.py) — this
client itself does not enforce that gate, since it has no notion of config entries.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from homeassistant.core import HomeAssistant

from .const import REVX_API_BASE

_LOGGER = logging.getLogger(__name__)


class RevolutXAuthError(Exception):
    """Raised on 401/403 responses (bad API key / signature / IP allowlist)."""


class RevolutXAPIError(Exception):
    """Raised on any other non-2xx response."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def load_private_key(pem_text: str) -> Ed25519PrivateKey:
    """Parse a PEM-encoded Ed25519 private key."""
    key = load_pem_private_key(pem_text.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Private key is not an Ed25519 key")
    return key


def _query_string(params: dict[str, Any] | None) -> str:
    if not params:
        return ""
    parts = [f"{k}={v}" for k, v in params.items() if v is not None]
    return "&".join(parts)


def sign_request(
    private_key: Ed25519PrivateKey,
    timestamp_ms: int,
    method: str,
    path: str,
    query: str,
    body: str,
) -> str:
    """Build and sign the Revolut X request digest, return base64 signature."""
    message = f"{timestamp_ms}{method.upper()}{path}{query}{body}".encode("utf-8")
    signature = private_key.sign(message)
    return base64.b64encode(signature).decode("ascii")


class RevolutXClient:
    """Thin async wrapper around the Revolut X REST API.

    `hass`, if provided, is used only by CPU-bound helpers (the grid-backtest
    engine in backtest.py) to offload work via `hass.async_add_executor_job` —
    it plays no role in signing or dispatching HTTP requests.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        private_key: Ed25519PrivateKey,
        base_url: str = REVX_API_BASE,
        hass: HomeAssistant | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._private_key = private_key
        self._base_url = base_url.rstrip("/")
        self.hass = hass

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        query = _query_string(params)
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{query}"

        headers = {"Content-Type": "application/json"}
        if auth:
            timestamp_ms = int(time.time() * 1000)
            full_path = f"/api/1.0{path}"
            signature = sign_request(
                self._private_key, timestamp_ms, method, full_path, query, body_str
            )
            headers |= {
                "X-Revx-API-Key": self._api_key,
                "X-Revx-Timestamp": str(timestamp_ms),
                "X-Revx-Signature": signature,
            }

        start = time.monotonic()
        async with self._session.request(
            method, url, headers=headers, data=body_str if body is not None else None
        ) as resp:
            text = await resp.text()
            elapsed_ms = (time.monotonic() - start) * 1000
            _LOGGER.debug(
                "Revolut X API %s %s%s -> %s (%.0fms)",
                method,
                path,
                f"?{query}" if query else "",
                resp.status,
                elapsed_ms,
            )
            if resp.status in (401, 403):
                _LOGGER.debug("Revolut X API error response body: %s", text[:500])
                raise RevolutXAuthError(text or f"HTTP {resp.status}")
            if resp.status >= 400:
                _LOGGER.debug("Revolut X API error response body: %s", text[:500])
                raise RevolutXAPIError(resp.status, text)
            if not text:
                return None
            return json.loads(text)

    # -- Account -----------------------------------------------------

    async def get_balances(self) -> Any:
        return await self._request("GET", "/balances")

    # -- Configuration -------------------------------------------------

    async def get_currencies(self) -> Any:
        return await self._request("GET", "/configuration/currencies")

    async def get_pairs(self) -> Any:
        return await self._request("GET", "/configuration/pairs")

    # -- Orders (read-only) --------------------------------------------

    async def get_active_orders(
        self,
        symbols: str | None = None,
        order_states: str | None = None,
        order_types: str | None = None,
        side: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            "/orders/active",
            params={
                "symbols": symbols,
                "order_states": order_states,
                "order_types": order_types,
                "side": side,
                "cursor": cursor,
                "limit": limit,
            },
        )

    async def get_historical_orders(
        self,
        symbols: str | None = None,
        order_states: str | None = None,
        order_types: str | None = None,
        start_date: int | None = None,
        end_date: int | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            "/orders/historical",
            params={
                "symbols": symbols,
                "order_states": order_states,
                "order_types": order_types,
                "start_date": start_date,
                "end_date": end_date,
                "cursor": cursor,
                "limit": limit,
            },
        )

    async def get_order(self, venue_order_id: str) -> Any:
        return await self._request("GET", f"/orders/{venue_order_id}")

    async def get_order_fills(self, venue_order_id: str) -> Any:
        return await self._request("GET", f"/orders/fills/{venue_order_id}")

    # -- Orders (write) --------------------------------------------------

    async def place_order(
        self, client_order_id: str, symbol: str, side: str, order_configuration: dict[str, Any]
    ) -> Any:
        return await self._request(
            "POST",
            "/orders",
            body={
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side,
                "order_configuration": order_configuration,
            },
        )

    async def replace_order(self, venue_order_id: str, client_order_id: str, **fields: Any) -> Any:
        body = {"client_order_id": client_order_id, **{k: v for k, v in fields.items() if v is not None}}
        return await self._request("PUT", f"/orders/{venue_order_id}", body=body)

    async def cancel_order(self, venue_order_id: str) -> Any:
        return await self._request("DELETE", f"/orders/{venue_order_id}")

    async def cancel_all_orders(self) -> Any:
        return await self._request("DELETE", "/orders")

    # -- Trades ----------------------------------------------------------

    async def get_all_trades(
        self,
        symbol: str,
        start_date: int | None = None,
        end_date: int | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            f"/trades/all/{symbol}",
            params={
                "start_date": start_date,
                "end_date": end_date,
                "cursor": cursor,
                "limit": limit,
            },
        )

    async def get_private_trades(
        self,
        symbol: str,
        start_date: int | None = None,
        end_date: int | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            f"/trades/private/{symbol}",
            params={
                "start_date": start_date,
                "end_date": end_date,
                "cursor": cursor,
                "limit": limit,
            },
        )

    # -- Market data -------------------------------------------------------

    async def get_order_book(self, symbol: str, limit: int | None = None) -> Any:
        return await self._request(
            "GET", f"/order-book/{symbol}", params={"limit": limit}
        )

    async def get_candles(
        self,
        symbol: str,
        interval: int | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            f"/candles/{symbol}",
            params={"interval": interval, "since": since, "until": until},
        )

    async def get_tickers(self, symbols: str | None = None) -> Any:
        return await self._request("GET", "/tickers", params={"symbols": symbols})

    # -- Public (unauthenticated) -----------------------------------------

    async def get_public_last_trades(self) -> Any:
        return await self._request("GET", "/public/last-trades", auth=False)

    async def get_public_order_book(self, symbol: str) -> Any:
        return await self._request(
            "GET", f"/public/order-book/{symbol}", auth=False
        )
