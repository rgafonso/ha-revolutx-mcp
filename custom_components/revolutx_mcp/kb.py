"""Static Revolut X knowledge-base content, exposed as `list_kb_articles` /
`search_kb` MCP tools.

This is original, short-form content written for this project — not a copy of
Revolut's own help-center articles or of the upstream `revolut-x-api` repo's
bundled article text (which is copyrighted and wasn't reproducible here anyway).
Treat it as a quick factual pointer, not an authoritative source: each entry
ends with a link to Revolut's real help center, which is the source of truth
and the only place that reflects current fees/policies.

`search_kb` does no runtime text matching — the calling LLM picks one of the
fixed `KB_ARTICLES` keys itself (constrained via the tool's JSON Schema `enum`),
using the per-topic `description` strings to classify the user's question. This
mirrors the upstream MCP server's own design for this feature.
"""
from __future__ import annotations

HELP_CENTER_POINTER = (
    "For current details, see Revolut's official help center: https://www.revolut.com/help/"
)

KB_ARTICLES: dict[str, dict[str, str]] = {
    "fees": {
        "description": "User asks about trading fees, withdrawal fees, network fees, or how much it "
        "costs to trade or move crypto.",
        "content": (
            "Revolut X charges a trading fee on executed orders, and network fees apply when "
            "withdrawing crypto to an external wallet (these vary by asset and network "
            "conditions). Revolut X is a separate platform from the main Revolut app's crypto "
            "feature, and its fee schedule is set independently. " + HELP_CENTER_POINTER
        ),
    },
    "order_types": {
        "description": "User asks about the types of orders on Revolut X: market, limit, take profit, "
        "stop loss, TP/SL, or conditional orders.",
        "content": (
            "Revolut X supports market orders (fill immediately at the best available price) and "
            "limit orders (fill only at a specified price or better). Conditional orders — "
            "including take-profit and stop-loss (TP/SL) — trigger a market or limit order once a "
            "chosen trigger price is reached, and are visible as read-only order records once "
            "placed via the Revolut X app. " + HELP_CENTER_POINTER
        ),
    },
    "failed_orders": {
        "description": "User's order was cancelled, rejected, or failed to execute.",
        "content": (
            "An order can fail or get rejected for reasons such as insufficient balance, the "
            "price moving outside a limit order's bounds, a post-only order that would have "
            "matched immediately (and so was rejected instead of executing as a taker), or the "
            "trading pair being temporarily unavailable. Use get_order or get_historical_orders "
            "on this MCP server to check a specific order's status and any rejection reason. "
            + HELP_CENTER_POINTER
        ),
    },
    "locked_balances": {
        "description": "User's balance is locked, unavailable, or reserved by an open order.",
        "content": (
            "Funds committed to an open limit, conditional, or TP/SL order are reserved and "
            "excluded from your available (spendable) balance until that order fills or is "
            "cancelled — get_balances on this MCP server reports both available and reserved "
            "amounts. Cancelling the order (or waiting for it to fill or expire) releases the "
            "reserved funds. " + HELP_CENTER_POINTER
        ),
    },
    "deposits_withdrawals": {
        "description": "User wants to deposit, top up, or withdraw crypto or fiat, or move funds "
        "to/from their Revolut X account.",
        "content": (
            "Deposits and withdrawals on Revolut X are managed from the Revolut X app itself, not "
            "through this MCP server — this integration is read-only for account activity aside "
            "from the order-placement tools it optionally exposes, and does not support "
            "transfers, deposits, or withdrawals at all. Check the Revolut X app for deposit "
            "addresses, top-up options, and withdrawal status. " + HELP_CENTER_POINTER
        ),
    },
    "unified_balance": {
        "description": "User asks about their crypto balance across Revolut and Revolut X, or how "
        "balances relate between the two.",
        "content": (
            "Revolut X is a separate trading platform from the crypto feature inside the main "
            "Revolut app; balances between the two are not automatically the same account. "
            "get_balances on this MCP server reports Revolut X's own account balances only. "
            + HELP_CENTER_POINTER
        ),
    },
    "why_cant_i_trade": {
        "description": "User cannot trade or place orders on Revolut X — insufficient funds, "
        "maintenance, or other blocking issues.",
        "content": (
            "Common reasons trading is blocked: insufficient available balance for the order size "
            "(see the locked_balances topic if funds appear tied up), the trading pair being "
            "paused or delisted (get_pairs on this MCP server reports each pair's status), "
            "scheduled maintenance, or account-level restrictions. " + HELP_CENTER_POINTER
        ),
    },
    "crypto_safety": {
        "description": "User asks whether their crypto is safe, about custody, cold storage, or "
        "investment risk.",
        "content": (
            "Crypto assets are volatile and carry investment risk; Revolut X's crypto services are "
            "provided by a regulated entity within the Revolut group, with custody arrangements "
            "described in Revolut's terms. This is general information, not financial advice. "
            + HELP_CENTER_POINTER
        ),
    },
    "crypto_services_provider": {
        "description": "User asks who provides Revolut's crypto services, or about regulatory status.",
        "content": (
            "Revolut X's crypto trading services are provided by a Revolut group entity licensed "
            "for crypto asset services in the relevant jurisdiction; the specific legal entity and "
            "licence depend on the country you're using Revolut X from. " + HELP_CENTER_POINTER
        ),
    },
    "legal_links": {
        "description": "User asks for legal documents, terms and conditions, trading rules, or "
        "official policy pages.",
        "content": (
            "Revolut X's terms and conditions, trading rules, and fee schedule are published on "
            "Revolut's official site and app — this MCP server doesn't host or mirror those "
            "documents. " + HELP_CENTER_POINTER
        ),
    },
}


def list_articles() -> list[dict[str, str]]:
    return [{"intent": key, "description": article["description"]} for key, article in KB_ARTICLES.items()]


def get_article(intent: str) -> str | None:
    article = KB_ARTICLES.get(intent)
    return article["content"] if article else None
