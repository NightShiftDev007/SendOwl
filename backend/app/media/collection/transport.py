"""Bounded HTTP transport for SandOwl-owned public media collection."""

import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.media.collection.errors import MediaCollectionError

MAXIMUM_RESPONSE_BYTES = 5_000_000
DEFAULT_TIMEOUT_SECONDS = 30
USER_AGENT = "SandOwlCollector/1.0 (+http://localhost:3200/)"
DOCKER_DESKTOP_DNS_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")
DOCKER_DESKTOP_DNS_PROXY_ENV = "MEDIA_COLLECTION_ALLOW_DOCKER_DESKTOP_DNS_PROXY"


class MediaFetchError(MediaCollectionError):
    """Raised when a public media URL cannot be fetched safely."""


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    url: str
    body: str
    status_code: int
    content_type: str
    etag: str | None
    last_modified: str | None


def _docker_desktop_dns_proxy_allowed() -> bool:
    raw = os.environ.get(DOCKER_DESKTOP_DNS_PROXY_ENV, "false").strip().lower()
    if raw not in {"true", "false"}:
        raise MediaFetchError(f"{DOCKER_DESKTOP_DNS_PROXY_ENV} must be true or false")
    return raw == "true"


def _validate_public_host(hostname: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise MediaFetchError(f"media hostname could not be resolved: {hostname}") from error
    if not addresses:
        raise MediaFetchError(f"media hostname resolved to no addresses: {hostname}")
    allow_docker_desktop_proxy = _docker_desktop_dns_proxy_allowed()
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_global:
            continue
        if allow_docker_desktop_proxy and ip in DOCKER_DESKTOP_DNS_PROXY_NETWORK:
            continue
        raise MediaFetchError("media collection refuses non-public network addresses")


def validate_public_media_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise MediaFetchError("media URL must be HTTP(S) without credentials or fragment")
    _validate_public_host(parsed.hostname)
    return url


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_media_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_public_document(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> FetchedDocument:
    validate_public_media_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "application/rss+xml, application/atom+xml, text/html, application/xml;q=0.9, */*;q=0.2"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    request = Request(url, headers=headers, method="GET")
    opener = build_opener(_PublicRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            raw = response.read(MAXIMUM_RESPONSE_BYTES + 1)
            if len(raw) > MAXIMUM_RESPONSE_BYTES:
                raise MediaFetchError("media response exceeded the 5 MB collection limit")
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            body = raw.decode(charset, errors="replace")
            final_url = str(response.geturl())
            validate_public_media_url(final_url)
            return FetchedDocument(
                url=final_url,
                body=body,
                status_code=int(response.status),
                content_type=content_type,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
    except HTTPError as error:
        if error.code == 304:
            final_url = str(error.geturl())
            validate_public_media_url(final_url)
            return FetchedDocument(
                url=final_url,
                body="",
                status_code=304,
                content_type=error.headers.get_content_type(),
                etag=error.headers.get("ETag") or etag,
                last_modified=error.headers.get("Last-Modified") or last_modified,
            )
        raise MediaFetchError(f"media request returned HTTP {error.code}") from error
    except (TimeoutError, URLError) as error:
        raise MediaFetchError(f"media request failed: {type(error).__name__}") from error
