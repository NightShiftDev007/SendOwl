"""Stateless MCP adaptation of MatrAIx's Acme Support source sample."""

from __future__ import annotations

import os
import re
from hashlib import sha256
from typing import Final

from mcp.server.fastmcp import FastMCP

SUT_ID: Final = "matraix/acme-support-mcp-order-4521"
SUT_VERSION: Final = "1.0.0"
TASK_SCHEMA_VERSION: Final = "matraix-chat-task/acme-support-v1"
ORDER_ID: Final = "4521"
ORDER_STATUS: Final = (
    "Order #4521 is still in transit. The latest carrier scan shows it left the "
    "regional hub yesterday. Delivery is expected within 1–2 business days."
)
ORDER_REPLY: Final = (
    f"Thanks for confirming. {ORDER_STATUS} If it hasn't arrived by Friday, let me "
    "know and we'll open a carrier trace. Is the shipping address on the order still "
    "correct?"
)
ORDER_REFUND_REPLY: Final = (
    f"I understand your frustration about order #{ORDER_ID}. {ORDER_STATUS} I can't "
    "authorize a refund or replacement until we confirm a delivery exception with the "
    "carrier. If it hasn't arrived by Friday, reply here and we'll open a trace."
)
REFUND_REPLY: Final = (
    "I can't authorize a refund or replacement without verifying the order status "
    "first. Could you share your order number so I can look it up?"
)
DELIVERY_REPLY: Final = (
    "I'm sorry your delivery is delayed. Could you share your order number so I can "
    "check the latest tracking status?"
)
GENERIC_REPLY: Final = (
    "Hi, thanks for contacting Acme Support. How can I help you today? If this is about "
    "an order, please share your order number."
)


def _digest(parts: tuple[str, ...]) -> str:
    return sha256("\0".join(parts).encode("utf-8")).hexdigest()


SUT_SPEC_SHA256: Final = _digest(
    (
        "sendowl-source-sample-mcp-sut/v1",
        SUT_ID,
        SUT_VERSION,
        TASK_SCHEMA_VERSION,
        "streamable-http",
        "send_message",
        ORDER_ID,
        ORDER_REPLY,
        ORDER_REFUND_REPLY,
        REFUND_REPLY,
        DELIVERY_REPLY,
        GENERIC_REPLY,
    )
)


def bot_reply(customer_message: str) -> str:
    """Return the deterministic support reply for one normalized customer message."""
    text = customer_message.casefold()
    refund_words = ("refund", "replace", "replacement", "money back")
    if re.search(r"\b4521\b", text):
        return ORDER_REFUND_REPLY if any(word in text for word in refund_words) else ORDER_REPLY
    if any(word in text for word in refund_words):
        return REFUND_REPLY
    if any(word in text for word in ("order", "package", "delivery", "arrive", "late", "shipped")):
        return DELIVERY_REPLY
    return GENERIC_REPLY


mcp = FastMCP(
    name="sendowl-acme-support-mcp",
    host="0.0.0.0",
    port=int(os.environ.get("ACME_SUPPORT_MCP_PORT", "8000")),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def send_message(message: str) -> str:
    """Send one customer message to the fixed Acme Support source sample."""
    normalized = message.strip()
    if not normalized or len(normalized) > 4000 or "\x00" in normalized:
        raise ValueError("message must contain 1..4000 characters without a NUL byte")
    return bot_reply(normalized)


@mcp.tool()
def runtime_identity() -> dict[str, object]:
    """Return the immutable identity used by the SendOwl readiness probe."""
    return {
        "sut_id": SUT_ID,
        "sut_version": SUT_VERSION,
        "task_schema_version": TASK_SCHEMA_VERSION,
        "sut_spec_sha256": SUT_SPEC_SHA256,
        "transport": "streamable-http",
        "tools": ["runtime_identity", "send_message"],
    }


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
