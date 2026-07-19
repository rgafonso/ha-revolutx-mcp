"""Minimal MCP (Model Context Protocol) JSON-RPC 2.0 dispatch.

Hand-rolled rather than depending on the `mcp` PyPI package: the surface area here
is small (one read-only tool per Revolut X REST endpoint), so a full SDK dependency
isn't worth adding to a HACS manifest. Implements just what a client needs for the
`tools` capability: `initialize`, `tools/list`, `tools/call`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .const import MCP_PROTOCOL_VERSION, SERVER_NAME
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[RevolutXClient, dict[str, Any]], Awaitable[Any]]

    def mcp_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_STR = {"type": "string"}
_INT = {"type": "integer"}


def _tools() -> list[Tool]:
    return [
        Tool(
            "get_balances",
            "Get all crypto and fiat account balances for the authenticated user.",
            _schema({}),
            lambda c, a: c.get_balances(),
        ),
        Tool(
            "get_currencies",
            "Get configuration (name, scale, status) for all currencies on the exchange.",
            _schema({}),
            lambda c, a: c.get_currencies(),
        ),
        Tool(
            "get_pairs",
            "Get configuration (min/max order size, step sizes, status) for all traded currency pairs.",
            _schema({}),
            lambda c, a: c.get_pairs(),
        ),
        Tool(
            "get_active_orders",
            "Get the authenticated user's active (open) orders, optionally filtered.",
            _schema(
                {
                    "symbols": {**_STR, "description": "Comma-separated pairs, e.g. BTC-USD,ETH-USD"},
                    "order_states": {**_STR, "description": "Comma-separated: pending_new,new,partially_filled"},
                    "order_types": {**_STR, "description": "Comma-separated: limit,conditional,tpsl"},
                    "side": {**_STR, "description": "buy or sell"},
                    "cursor": {**_STR, "description": "Pagination cursor from a previous response"},
                    "limit": {**_INT, "description": "Max records, 1-100 (default 100)"},
                }
            ),
            lambda c, a: c.get_active_orders(
                symbols=a.get("symbols"),
                order_states=a.get("order_states"),
                order_types=a.get("order_types"),
                side=a.get("side"),
                cursor=a.get("cursor"),
                limit=a.get("limit"),
            ),
        ),
        Tool(
            "get_historical_orders",
            "Get the authenticated user's completed orders (filled/cancelled/rejected/replaced). "
            "start_date/end_date span at most 1 week.",
            _schema(
                {
                    "symbols": {**_STR, "description": "Comma-separated pairs, e.g. BTC-USD,ETH-USD"},
                    "order_states": {**_STR, "description": "Comma-separated: filled,cancelled,rejected,replaced"},
                    "order_types": {**_STR, "description": "Comma-separated: market,limit"},
                    "start_date": {**_INT, "description": "Unix epoch ms"},
                    "end_date": {**_INT, "description": "Unix epoch ms"},
                    "cursor": {**_STR, "description": "Pagination cursor from a previous response"},
                    "limit": {**_INT, "description": "Max records, 1-100 (default 100)"},
                }
            ),
            lambda c, a: c.get_historical_orders(
                symbols=a.get("symbols"),
                order_states=a.get("order_states"),
                order_types=a.get("order_types"),
                start_date=a.get("start_date"),
                end_date=a.get("end_date"),
                cursor=a.get("cursor"),
                limit=a.get("limit"),
            ),
        ),
        Tool(
            "get_order",
            "Retrieve a specific order by its venue order ID.",
            _schema({"venue_order_id": _STR}, ["venue_order_id"]),
            lambda c, a: c.get_order(a["venue_order_id"]),
        ),
        Tool(
            "get_order_fills",
            "Get the fills (trade executions) for a specific order.",
            _schema({"venue_order_id": _STR}, ["venue_order_id"]),
            lambda c, a: c.get_order_fills(a["venue_order_id"]),
        ),
        Tool(
            "get_all_trades",
            "Get all market trades (not just the user's own) for a symbol. Requires auth despite "
            "being public data; start_date/end_date span at most 1 week.",
            _schema(
                {
                    "symbol": {**_STR, "description": "e.g. BTC-USD"},
                    "start_date": {**_INT, "description": "Unix epoch ms"},
                    "end_date": {**_INT, "description": "Unix epoch ms"},
                    "cursor": _STR,
                    "limit": {**_INT, "description": "Max records, 1-100 (default 100)"},
                },
                ["symbol"],
            ),
            lambda c, a: c.get_all_trades(
                a["symbol"],
                start_date=a.get("start_date"),
                end_date=a.get("end_date"),
                cursor=a.get("cursor"),
                limit=a.get("limit"),
            ),
        ),
        Tool(
            "get_private_trades",
            "Get the authenticated user's own trade history for a symbol. start_date/end_date span "
            "at most 1 week.",
            _schema(
                {
                    "symbol": {**_STR, "description": "e.g. BTC-USD"},
                    "start_date": {**_INT, "description": "Unix epoch ms"},
                    "end_date": {**_INT, "description": "Unix epoch ms"},
                    "cursor": _STR,
                    "limit": {**_INT, "description": "Max records, 1-100 (default 100)"},
                },
                ["symbol"],
            ),
            lambda c, a: c.get_private_trades(
                a["symbol"],
                start_date=a.get("start_date"),
                end_date=a.get("end_date"),
                cursor=a.get("cursor"),
                limit=a.get("limit"),
            ),
        ),
        Tool(
            "get_order_book",
            "Get the current order book snapshot (bids/asks) for a symbol.",
            _schema(
                {
                    "symbol": {**_STR, "description": "e.g. BTC-USD"},
                    "limit": {**_INT, "description": "Depth, 1-20 (default 20)"},
                },
                ["symbol"],
            ),
            lambda c, a: c.get_order_book(a["symbol"], limit=a.get("limit")),
        ),
        Tool(
            "get_candles",
            "Get historical OHLCV candle data for a symbol. (until - since) / interval must not "
            "exceed 100 candles.",
            _schema(
                {
                    "symbol": {**_STR, "description": "e.g. BTC-USD"},
                    "interval": {**_INT, "description": "Candle interval in minutes (default 5)"},
                    "since": {**_INT, "description": "Start, Unix epoch ms"},
                    "until": {**_INT, "description": "End, Unix epoch ms (default now)"},
                },
                ["symbol"],
            ),
            lambda c, a: c.get_candles(
                a["symbol"], interval=a.get("interval"), since=a.get("since"), until=a.get("until")
            ),
        ),
        Tool(
            "get_tickers",
            "Get the latest market data snapshot (bid/ask/mid/last price) for all or specific pairs.",
            _schema({"symbols": {**_STR, "description": "Comma-separated pairs, e.g. BTC-USD,ETH-USD"}}),
            lambda c, a: c.get_tickers(symbols=a.get("symbols")),
        ),
        Tool(
            "get_public_last_trades",
            "Get the latest 100 trades executed on Revolut X. No authentication required.",
            _schema({}),
            lambda c, a: c.get_public_last_trades(),
        ),
        Tool(
            "get_public_order_book",
            "Get the current order book (up to 5 price levels per side) for a symbol. No "
            "authentication required.",
            _schema({"symbol": {**_STR, "description": "e.g. BTC-USD"}}, ["symbol"]),
            lambda c, a: c.get_public_order_book(a["symbol"]),
        ),
    ]


TOOLS: dict[str, Tool] = {tool.name: tool for tool in _tools()}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def handle_message(client: RevolutXClient, message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC 2.0 request and return a response, or None for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method is None:
        return _error(request_id, -32600, "Invalid Request: missing 'method'")

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
            },
        )

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": [t.mcp_definition() for t in TOOLS.values()]})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = TOOLS.get(tool_name)
        if tool is None:
            return _error(request_id, -32602, f"Unknown tool: {tool_name}")
        try:
            data = await tool.handler(client, arguments)
        except (RevolutXAuthError, RevolutXAPIError) as err:
            _LOGGER.warning("Revolut X API error calling tool %s: %s", tool_name, err)
            return _result(
                request_id,
                {"content": [{"type": "text", "text": str(err)}], "isError": True},
            )
        except KeyError as err:
            return _error(request_id, -32602, f"Missing required argument: {err}")
        return _result(request_id, {"content": [{"type": "text", "text": _to_text(data)}]})

    return _error(request_id, -32601, f"Method not found: {method}")


def _to_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
