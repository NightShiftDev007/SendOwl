"""Deterministic HTTP SUT adapted from MatrAIx's Acme Support sample.

This is a source-sample application used to exercise the Chatbot Evaluation
runtime. It is not a production customer-support system and stores no shared
conversation state; the SendOwl worker owns each trial transcript.
"""

from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final, Never, TypedDict

SUT_ID: Final = "matraix/acme-support-order-4521"
SUT_VERSION: Final = "1.0.0"
TASK_SCHEMA_VERSION: Final = "matraix-chat-task/acme-support-v1"
ORDER_ID: Final = "4521"
MAX_MESSAGE_LENGTH: Final = 4000
MAX_REQUEST_BYTES: Final = 16_384
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


class ReadyResponse(TypedDict):
    status: str
    sut_id: str
    sut_version: str
    task_schema_version: str
    sut_spec_sha256: str
    capabilities: list[str]


def _canonical_sut_spec_json() -> str:
    return json.dumps(
        {
            "capabilities": ["text_chat"],
            "order_id": ORDER_ID,
            "reply_policy": {
                "delivery_reply": DELIVERY_REPLY,
                "generic_reply": GENERIC_REPLY,
                "order_refund_reply": ORDER_REFUND_REPLY,
                "order_reply": ORDER_REPLY,
                "refund_reply": REFUND_REPLY,
            },
            "schema": "sendowl-source-sample-sut/v1",
            "sut_id": SUT_ID,
            "sut_version": SUT_VERSION,
            "task_schema_version": TASK_SCHEMA_VERSION,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


SUT_SPEC_SHA256: Final = sha256(_canonical_sut_spec_json().encode("utf-8")).hexdigest()


def bot_reply(customer_message: str) -> str:
    """Return the exact deterministic source-sample reply for one message."""

    text = customer_message.casefold()
    refund_words = ("refund", "replace", "replacement", "money back")

    if re.search(r"\b4521\b", text):
        if any(word in text for word in refund_words):
            return ORDER_REFUND_REPLY
        return ORDER_REPLY

    if any(word in text for word in refund_words):
        return REFUND_REPLY

    if any(word in text for word in ("order", "package", "delivery", "arrive", "late", "shipped")):
        return DELIVERY_REPLY

    return GENERIC_REPLY


def ready_response() -> ReadyResponse:
    probe = bot_reply("hello")
    if not probe.strip():
        raise RuntimeError("Acme Support source-sample reply probe returned empty content")
    return {
        "status": "ready",
        "sut_id": SUT_ID,
        "sut_version": SUT_VERSION,
        "task_schema_version": TASK_SCHEMA_VERSION,
        "sut_spec_sha256": SUT_SPEC_SHA256,
        "capabilities": ["text_chat"],
    }


class AcmeSupportRequestHandler(BaseHTTPRequestHandler):
    """Strict JSON boundary for the isolated source-sample application."""

    server_version = "SendOwlAcmeSupport/1.0"
    sys_version = ""

    def _write_json(self, status: HTTPStatus, body: object) -> None:
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _read_message(self) -> str:
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json")
        length_text = self.headers.get("Content-Length")
        if length_text is None or not length_text.isdecimal():
            raise ValueError("Content-Length must be a non-negative integer")
        length = int(length_text)
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError(f"request body must contain 1..{MAX_REQUEST_BYTES} bytes")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("request body must be valid UTF-8 JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"message"}:
            raise ValueError("request body must contain only the message field")
        message = payload["message"]
        if not isinstance(message, str):
            raise ValueError("message must be a string")
        normalized = message.strip()
        if not normalized or len(normalized) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"message must contain 1..{MAX_MESSAGE_LENGTH} characters")
        return normalized

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok", "sut_id": SUT_ID})
            return
        if self.path == "/ready":
            self._write_json(HTTPStatus.OK, ready_response())
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "endpoint not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/messages":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "endpoint not found"})
            return
        try:
            message = self._read_message()
        except ValueError as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self._write_json(HTTPStatus.OK, {"reply": bot_reply(message)})

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), AcmeSupportRequestHandler)


def main() -> Never:
    host = os.environ.get("ACME_SUPPORT_HOST", "0.0.0.0")
    port_text = os.environ.get("ACME_SUPPORT_PORT", "8000")
    if not port_text.isdecimal() or not 1 <= int(port_text) <= 65_535:
        raise RuntimeError("ACME_SUPPORT_PORT must be an integer from 1 through 65535")
    create_server(host, int(port_text)).serve_forever()
    raise AssertionError("Acme Support source-sample server stopped unexpectedly")


if __name__ == "__main__":
    main()
