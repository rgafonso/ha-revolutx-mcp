"""Minimal MCP (Model Context Protocol) JSON-RPC 2.0 dispatch.

Hand-rolled rather than depending on the `mcp` PyPI package: the surface area here
is small (one read-only tool per Revolut X REST endpoint), so a full SDK dependency
isn't worth adding to a HACS manifest. Implements just what a client needs for the
`tools` capability: `initialize`, `tools/list`, `tools/call`.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import backtest, kb
from .const import MCP_PROTOCOL_VERSION, SERVER_NAME
from .revolut_client import RevolutXAPIError, RevolutXAuthError, RevolutXClient

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[RevolutXClient, dict[str, Any]], Awaitable[Any]]
    requires_trading: bool = False
    # MCP tool annotations (spec 2025-03-26+, unchanged through 2025-11-25) — hints only,
    # clients must treat them as untrusted, but they're what lets a client like Claude's
    # connector UI split tools into read-only vs write/delete permission buckets. Defaults
    # mirror the spec's own defaults (err toward "assume it's a write" for anything left
    # unset) rather than defaulting to the read-only-friendly values.
    read_only_hint: bool = False
    destructive_hint: bool = True
    idempotent_hint: bool = False
    open_world_hint: bool = True

    def mcp_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "readOnlyHint": self.read_only_hint,
                "destructiveHint": self.destructive_hint,
                "idempotentHint": self.idempotent_hint,
                "openWorldHint": self.open_world_hint,
            },
        }


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_NUM = {"type": "number"}


def _normalize_order_response(data: Any) -> Any:
    """place_order/replace_order responses are documented as {"data": {...}} but
    the OpenAPI spec's own example shows `data` as a one-element array instead —
    normalize to the singular-object shape either way."""
    if not isinstance(data, dict):
        return data
    inner = data.get("data")
    if isinstance(inner, list):
        return {**data, "data": inner[0] if inner else None}
    return data


async def _place_order(client: RevolutXClient, args: dict[str, Any]) -> Any:
    client_order_id = args.get("client_order_id") or str(uuid.uuid4())
    data = await client.place_order(
        client_order_id, args["symbol"], args["side"], args["order_configuration"]
    )
    return _normalize_order_response(data)


async def _replace_order(client: RevolutXClient, args: dict[str, Any]) -> Any:
    client_order_id = args.get("client_order_id") or str(uuid.uuid4())
    data = await client.replace_order(
        args["venue_order_id"],
        client_order_id,
        price=args.get("price"),
        base_size=args.get("base_size"),
        quote_size=args.get("quote_size"),
        time_in_force=args.get("time_in_force"),
        execution_instructions=args.get("execution_instructions"),
    )
    return _normalize_order_response(data)


async def _list_kb_articles(client: RevolutXClient, args: dict[str, Any]) -> Any:
    # kb.list_articles() is plain sync code (no API call) — wrapped in an async
    # function since every Tool.handler is awaited uniformly in handle_message.
    return kb.list_articles()


async def _search_kb(client: RevolutXClient, args: dict[str, Any]) -> Any:
    return kb.get_article(args["intent"]) or f"No article for intent: {args['intent']}"


def _tools() -> list[Tool]:
    return [
        Tool(
            "get_balances",
            "Get all crypto and fiat account balances for the authenticated user.",
            _schema({}),
            lambda c, a: c.get_balances(),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "get_currencies",
            "Get configuration (name, scale, status) for all currencies on the exchange.",
            _schema({}),
            lambda c, a: c.get_currencies(),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "get_pairs",
            "Get configuration (min/max order size, step sizes, status) for all traded currency pairs.",
            _schema({}),
            lambda c, a: c.get_pairs(),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
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
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
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
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "get_order",
            "Retrieve a specific order by its venue order ID.",
            _schema({"venue_order_id": _STR}, ["venue_order_id"]),
            lambda c, a: c.get_order(a["venue_order_id"]),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "get_order_fills",
            "Get the fills (trade executions) for a specific order.",
            _schema({"venue_order_id": _STR}, ["venue_order_id"]),
            lambda c, a: c.get_order_fills(a["venue_order_id"]),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
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
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
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
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
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
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
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
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "get_tickers",
            "Get the latest market data snapshot (bid/ask/mid/last price) for all or specific pairs.",
            _schema({"symbols": {**_STR, "description": "Comma-separated pairs, e.g. BTC-USD,ETH-USD"}}),
            lambda c, a: c.get_tickers(symbols=a.get("symbols")),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "get_public_last_trades",
            "Get the latest 100 trades executed on Revolut X. No authentication required.",
            _schema({}),
            lambda c, a: c.get_public_last_trades(),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "get_public_order_book",
            "Get the current order book (up to 5 price levels per side) for a symbol. No "
            "authentication required.",
            _schema({"symbol": {**_STR, "description": "e.g. BTC-USD"}}, ["symbol"]),
            lambda c, a: c.get_public_order_book(a["symbol"]),
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        # -- Orders (write) — gated behind the "Enable trading" option, see
        # mcp_dispatch.handle_message / __init__.py's CONF_TRADING_ENABLED ------
        Tool(
            "place_order",
            "⚠️ Places a REAL order using REAL funds on Revolut X. Confirm the symbol, side, "
            "size, and price with the user before calling this. Exactly one of limit/market "
            "must be given in order_configuration, and within it exactly one of base_size/"
            "quote_size.",
            _schema(
                {
                    "symbol": {**_STR, "description": "e.g. BTC-USD"},
                    "side": {**_STR, "description": "buy or sell"},
                    "order_configuration": {
                        "type": "object",
                        "description": 'Exactly one of {"limit": {"price", "base_size"?, '
                        '"quote_size"?, "time_in_force"?: "gtc"|"ioc", "execution_instructions"?: '
                        '["allow_taker"|"post_only", ...]}} or {"market": {"base_size"?, "quote_size"?}}',
                    },
                    "client_order_id": {
                        **_STR,
                        "description": "Idempotency key; auto-generated if omitted.",
                    },
                },
                ["symbol", "side", "order_configuration"],
            ),
            _place_order,
            requires_trading=True,
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        ),
        Tool(
            "replace_order",
            "⚠️ Modifies a REAL open order on Revolut X (cancels and replaces it). Confirm with "
            "the user first. Only price/base_size/quote_size/time_in_force/execution_instructions "
            "are replaceable — symbol/side cannot change. Omitted fields inherit from the "
            "original order. The venue_order_id changes as a result of this call.",
            _schema(
                {
                    "venue_order_id": {**_STR, "description": "ID of the order to replace"},
                    "client_order_id": {
                        **_STR,
                        "description": "New idempotency key for the replacement; auto-generated if omitted.",
                    },
                    "price": _STR,
                    "base_size": _STR,
                    "quote_size": _STR,
                    "time_in_force": {**_STR, "description": "gtc or ioc"},
                    "execution_instructions": {
                        "type": "array",
                        "items": {**_STR, "enum": ["allow_taker", "post_only"]},
                    },
                },
                ["venue_order_id"],
            ),
            _replace_order,
            requires_trading=True,
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=True,
        ),
        Tool(
            "cancel_order",
            "⚠️ Cancels a REAL open order on Revolut X. Confirm with the user first.",
            _schema({"venue_order_id": _STR}, ["venue_order_id"]),
            lambda c, a: c.cancel_order(a["venue_order_id"]),
            requires_trading=True,
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=True,
        ),
        Tool(
            "cancel_all_orders",
            "⚠️ Cancels EVERY open order on Revolut X account-wide — there is no symbol filter. "
            "Confirm with the user first.",
            _schema({}),
            lambda c, a: c.cancel_all_orders(),
            requires_trading=True,
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=True,
        ),
        # -- Knowledge base (static content, always available) ------------------
        Tool(
            "list_kb_articles",
            "List the fixed set of Revolut X help topics this server can answer from static "
            "content. Use this if unsure which intent to pass to search_kb.",
            _schema({}),
            _list_kb_articles,
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        Tool(
            "search_kb",
            "Get a short factual summary for one Revolut X help topic. Classify the user's "
            "question into the intent that best matches (see list_kb_articles for the full set "
            "with descriptions).",
            _schema(
                {"intent": {**_STR, "enum": list(kb.KB_ARTICLES), "description": "One of the fixed topic keys."}},
                ["intent"],
            ),
            _search_kb,
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        # -- Grid strategy backtest (historical simulation, no live orders) ------
        Tool(
            "grid_backtest",
            "Simulate a grid trading strategy against historical candle data. No live orders "
            "are placed — this is a pure historical simulation, not a prediction.",
            _schema(
                {
                    "symbol": {**_STR, "description": "e.g. BTC-USD"},
                    "grid_levels": {**_INT, "description": "Grid levels per side, 1-25 (default 5)"},
                    "range_pct": {**_STR, "description": '±range from start price as a percent, e.g. "10" (default "10")'},
                    "investment": {**_STR, "description": 'Quote-currency amount to simulate with (default "1000")'},
                    "resolution": {
                        **_STR,
                        "enum": list(backtest.RESOLUTION_MINUTES),
                        "description": "Candle resolution (default 1m)",
                    },
                    "days": {**_INT, "description": "History window in days, 1-365 (default 3)"},
                    "split_investment": {**_BOOL, "description": "Pre-fund sell-side levels for ranging markets (default false)"},
                    "trailing_up": {**_BOOL, "description": "Rebuild the grid when price exits the upper boundary (default false)"},
                    "stop_loss_price": {**_NUM, "description": "Absolute price; 0 disables (default 0)"},
                },
                ["symbol"],
            ),
            backtest.grid_backtest_tool,
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        Tool(
            "grid_optimize",
            "Sweep grid_levels x range_pct combinations against historical candle data and rank "
            "by total P&L. No live orders are placed — pure historical simulation.",
            _schema(
                {
                    "symbol": {**_STR, "description": "e.g. BTC-USD"},
                    "grid_levels_options": {**_STR, "description": 'CSV of per-side level counts, each 1-25 (default "3,5,8,10,15")'},
                    "range_pct_options": {**_STR, "description": 'CSV of ±range percents (default "3,5,7,10,12,15,20")'},
                    "investment": {**_STR, "description": 'Quote-currency amount to simulate with (default "1000")'},
                    "resolution": {
                        **_STR,
                        "enum": list(backtest.RESOLUTION_MINUTES),
                        "description": "Candle resolution (default 1m)",
                    },
                    "days": {**_INT, "description": "History window in days, 1-365 (default 3)"},
                    "split_investment": {**_BOOL, "description": "Pre-fund sell-side levels for ranging markets (default false)"},
                    "trailing_up": {**_BOOL, "description": "Rebuild the grid when price exits the upper boundary (default false)"},
                    "stop_loss_price": {**_NUM, "description": "Absolute price; 0 disables (default 0)"},
                    "top_n": {**_INT, "description": "Number of top results to return, 1-50 (default 10)"},
                },
                ["symbol"],
            ),
            backtest.grid_optimize_tool,
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
    ]


TOOLS: dict[str, Tool] = {tool.name: tool for tool in _tools()}
assert all(not t.read_only_hint for t in TOOLS.values() if t.requires_trading), (
    "A trading (requires_trading) tool must never be marked read_only_hint=True"
)


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def handle_message(
    client: RevolutXClient, message: dict[str, Any], trading_enabled: bool = False
) -> dict[str, Any] | None:
    """Time and log one JSON-RPC 2.0 request/response at DEBUG, delegating the
    actual dispatch to `_dispatch` — mirrors revolut_client.py's `_request`
    logging (method/outcome/duration, nothing sensitive), for the inbound
    side of this integration's own MCP server.
    """
    start = time.monotonic()
    response = await _dispatch(client, message, trading_enabled)
    elapsed_ms = (time.monotonic() - start) * 1000

    method = message.get("method")
    detail = ""
    if method == "tools/call":
        detail = f" tool={(message.get('params') or {}).get('name')}"
    outcome = "notification" if response is None else ("error" if "error" in response else "ok")
    _LOGGER.debug("MCP request %s%s -> %s (%.0fms)", method, detail, outcome, elapsed_ms)

    return response


async def _dispatch(
    client: RevolutXClient, message: dict[str, Any], trading_enabled: bool = False
) -> dict[str, Any] | None:
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
        visible = [t for t in TOOLS.values() if trading_enabled or not t.requires_trading]
        return _result(request_id, {"tools": [t.mcp_definition() for t in visible]})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = TOOLS.get(tool_name)
        if tool is None:
            return _error(request_id, -32602, f"Unknown tool: {tool_name}")
        if tool.requires_trading and not trading_enabled:
            # Same error as a genuinely nonexistent tool name — a client with
            # trading disabled shouldn't be able to tell "gated" from "doesn't exist".
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
        except ValueError as err:
            return _error(request_id, -32602, str(err))
        return _result(request_id, {"content": [{"type": "text", "text": _to_text(data)}]})

    return _error(request_id, -32601, f"Method not found: {method}")


def _to_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
