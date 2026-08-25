"""Allowlisted Playwright executor for the fixed MatrAIx quote-choice source task."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import urlparse
from uuid import UUID

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route, sync_playwright

TASK_ID: Final = "matraix/quotes-playwright-choice"
TASK_VERSION: Final = "1.0.0"
EXECUTOR_SCHEMA_VERSION: Final = "matraix-web-browser-executor/v1"
TARGET_ORIGIN: Final = "https://quotes.toscrape.com"
MAX_REQUEST_BYTES: Final = 1_024
MAX_RESPONSE_BYTES: Final = 1_048_576
NAVIGATION_TIMEOUT_MS: Final = 20_000
PAGE_COUNT: Final = 3
VIEWPORT: Final = {"width": 1280, "height": 900}
PAGE_PATH_PATTERN: Final = re.compile(r"^/(?:page/[1-9][0-9]*/)?$")
ARTIFACT_ROOT: Final = Path(os.environ.get("WEB_ARTIFACT_ROOT", "/web-artifacts"))


def _compact_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _executor_spec() -> dict[str, object]:
    return {
        "schema_version": EXECUTOR_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "task_version": TASK_VERSION,
        "target_origin": TARGET_ORIGIN,
        "page_count": PAGE_COUNT,
        "viewport": VIEWPORT,
        "browser": "chromium",
        "network_policy": "same-origin-only",
    }


EXECUTOR_SPEC_SHA256: Final = _sha256_bytes(_compact_json(_executor_spec()))


@dataclass(frozen=True)
class QuoteObservation:
    position: int
    quote_id: str
    text: str
    author: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class PageObservation:
    position: int
    url: str
    title: str
    screenshot_sha256: str
    quotes: tuple[QuoteObservation, ...]


def _valid_target_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "quotes.toscrape.com"
        and PAGE_PATH_PATTERN.fullmatch(parsed.path) is not None
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _route_request(route: Route) -> None:
    if _valid_target_url(route.request.url):
        route.continue_()
        return
    route.abort("blockedbyclient")


def _quote_id(text: str, author: str) -> str:
    return hashlib.sha256(f"{text}\0{author}".encode()).hexdigest()


def _read_quotes(page: Page, first_quote_position: int) -> tuple[QuoteObservation, ...]:
    rows = page.locator(".quote")
    count = rows.count()
    if count < 1 or count > 20:
        raise RuntimeError(f"quote page returned an invalid row count: {count}")
    quotes: list[QuoteObservation] = []
    for position in range(count):
        row = rows.nth(position)
        text = row.locator(".text").inner_text().strip()
        author = row.locator(".author").inner_text().strip()
        tags = tuple(tag.strip() for tag in row.locator(".tag").all_inner_texts())
        if not text or not author or len(text) > 2_000 or len(author) > 200:
            raise RuntimeError("quote page returned an invalid quote record")
        quotes.append(
            QuoteObservation(
                position=first_quote_position + position,
                quote_id=_quote_id(text, author),
                text=text,
                author=author,
                tags=tags,
            )
        )
    return tuple(quotes)


def _observe_page(
    page: Page,
    trial_directory: Path,
    page_position: int,
    first_quote_position: int,
) -> PageObservation:
    url = page.url
    if not _valid_target_url(url):
        raise RuntimeError("browser navigated outside the fixed Quotes source task")
    screenshot_path = trial_directory / f"page-{page_position}.png"
    screenshot = page.screenshot(path=str(screenshot_path), full_page=True)
    return PageObservation(
        position=page_position,
        url=url,
        title=page.title().strip(),
        screenshot_sha256=_sha256_bytes(screenshot),
        quotes=_read_quotes(page, first_quote_position),
    )


def _new_context(playwright: Playwright) -> tuple[Browser, BrowserContext]:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport=VIEWPORT,
        locale="en-US",
        timezone_id="UTC",
        java_script_enabled=True,
        service_workers="block",
    )
    context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    context.route("**/*", _route_request)
    return browser, context


def observe_quotes(trial_id: UUID) -> tuple[PageObservation, ...]:
    trial_directory = ARTIFACT_ROOT / str(trial_id)
    trial_directory.mkdir(mode=0o750, parents=False, exist_ok=False)
    with sync_playwright() as playwright:
        browser, context = _new_context(playwright)
        try:
            page = context.new_page()
            page.goto(f"{TARGET_ORIGIN}/", wait_until="domcontentloaded")
            observations: list[PageObservation] = []
            next_quote_position = 0
            for page_position in range(PAGE_COUNT):
                observation = _observe_page(
                    page,
                    trial_directory,
                    page_position,
                    next_quote_position,
                )
                observations.append(observation)
                next_quote_position += len(observation.quotes)
                if page_position + 1 == PAGE_COUNT:
                    break
                next_link = page.locator("li.next > a")
                if next_link.count() != 1:
                    raise RuntimeError("quote page did not expose the expected next-page link")
                next_link.click()
                page.wait_for_load_state("domcontentloaded")
            return tuple(observations)
        except BaseException:
            for path in trial_directory.glob("*.png"):
                path.unlink(missing_ok=True)
            trial_directory.rmdir()
            raise
        finally:
            context.close()
            browser.close()


def _parse_observation_request(raw: bytes) -> UUID:
    try:
        payload: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("request body must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"trial_id", "task_id", "task_version"}:
        raise ValueError("request body must contain only trial_id, task_id, and task_version")
    if payload["task_id"] != TASK_ID or payload["task_version"] != TASK_VERSION:
        raise ValueError("request task identity does not match the fixed executor contract")
    trial_id = payload["trial_id"]
    if not isinstance(trial_id, str):
        raise ValueError("trial_id must be a UUID string")
    try:
        return UUID(trial_id)
    except ValueError as error:
        raise ValueError("trial_id must be a valid UUID string") from error


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "SandOwlWebExecutor/1.0"

    def _write_json(self, status: HTTPStatus, payload: object) -> None:
        body = _compact_json(payload)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("executor response exceeded the fixed size limit")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/ready":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "route_not_found"})
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "status": "ready",
                "task_id": TASK_ID,
                "task_version": TASK_VERSION,
                "executor_schema_version": EXECUTOR_SCHEMA_VERSION,
                "executor_spec_sha256": EXECUTOR_SPEC_SHA256,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/quote-observations":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "route_not_found"})
            return
        content_length = self.headers.get("Content-Length", "")
        if not content_length.isdecimal() or int(content_length) > MAX_REQUEST_BYTES:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return
        if self.headers.get("Content-Type") != "application/json":
            self._write_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "json_required"})
            return
        try:
            trial_id = _parse_observation_request(self.rfile.read(int(content_length)))
            pages = observe_quotes(trial_id)
        except ValueError as error:
            self._write_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            return
        except FileExistsError:
            self._write_json(HTTPStatus.CONFLICT, {"error": "trial_artifacts_already_exist"})
            return
        except Exception as error:
            self.log_error("quote observation failed: %s", type(error).__name__)
            self._write_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "quote_observation_failed", "error_type": type(error).__name__},
            )
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "task_id": TASK_ID,
                "task_version": TASK_VERSION,
                "executor_schema_version": EXECUTOR_SCHEMA_VERSION,
                "executor_spec_sha256": EXECUTOR_SPEC_SHA256,
                "pages": tuple(asdict(page) for page in pages),
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        print(
            json.dumps(
                {"message": format % args, "client": self.client_address[0]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )


def main() -> None:
    ARTIFACT_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 8000), RequestHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
