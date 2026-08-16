from __future__ import annotations

import json
from threading import Thread
from typing import TypedDict, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from acme_support_sample.server import (
    SUT_ID,
    SUT_SPEC_SHA256,
    SUT_VERSION,
    TASK_SCHEMA_VERSION,
    bot_reply,
    create_server,
)


class ReadyResponse(TypedDict):
    status: str
    sut_id: str
    sut_version: str
    task_schema_version: str
    sut_spec_sha256: str
    capabilities: list[str]


def _get_json(url: str) -> object:
    with urlopen(url, timeout=2) as response:  # noqa: S310 - local test server only
        return json.loads(response.read())


def _post_json(url: str, body: object) -> object:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:  # noqa: S310 - local test server only
        return json.loads(response.read())


def test_source_sample_reply_reaches_the_order_resolution_path() -> None:
    first_reply = bot_reply("My NovaBuds delivery is late")
    second_reply = bot_reply("The order is 4521")

    assert "order number" in first_reply
    assert "still in transit" in second_reply
    assert "carrier trace" in second_reply


def test_source_sample_http_contract_is_strict_and_versioned() -> None:
    server = create_server("127.0.0.1", 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    try:
        ready = cast(ReadyResponse, _get_json(f"{base_url}/ready"))
        assert ready == {
            "status": "ready",
            "sut_id": SUT_ID,
            "sut_version": SUT_VERSION,
            "task_schema_version": TASK_SCHEMA_VERSION,
            "sut_spec_sha256": SUT_SPEC_SHA256,
            "capabilities": ["text_chat"],
        }
        assert _post_json(f"{base_url}/v1/messages", {"message": "Order 4521"}) == {
            "reply": bot_reply("Order 4521")
        }
        with pytest.raises(HTTPError) as error:
            _post_json(
                f"{base_url}/v1/messages",
                {"message": "Order 4521", "session": "shared"},
            )
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert not thread.is_alive()
