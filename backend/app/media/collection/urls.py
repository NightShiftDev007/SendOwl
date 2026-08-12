"""Stable URL identities and SHA-256 fingerprints for collected articles."""

import re
from hashlib import sha256
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.media.collection.errors import InvalidArticleUrlError

_TRACKING_PARAMETER_NAMES = frozenset(
    {
        "dclid",
        "fbclid",
        "from",
        "gclid",
        "msclkid",
        "ref",
        "referrer",
        "spm",
    }
)
_TRACKING_PARAMETER_PREFIXES = ("ref_", "utm_")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def calculate_sha256(value: str) -> str:
    """Return the lowercase SHA-256 digest of one exact UTF-8 string."""
    if not isinstance(value, str):
        raise TypeError(f"value must be str, got {type(value).__name__}")
    return sha256(value.encode("utf-8")).hexdigest()


def _is_tracking_parameter(name: str) -> bool:
    normalized_name = name.casefold()
    return normalized_name in _TRACKING_PARAMETER_NAMES or normalized_name.startswith(
        _TRACKING_PARAMETER_PREFIXES
    )


def _normalize_hostname(hostname: str, original_url: str) -> str:
    try:
        normalized_hostname = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise InvalidArticleUrlError(
            f"article URL contains an invalid internationalized hostname: {original_url!r}"
        ) from error
    if not normalized_hostname:
        raise InvalidArticleUrlError(f"article URL hostname is empty: {original_url!r}")
    if ":" in normalized_hostname:
        return f"[{normalized_hostname}]"
    return normalized_hostname


def _normalize_path(path: str, original_url: str) -> str:
    if _INVALID_PERCENT_ESCAPE.search(path) is not None:
        raise InvalidArticleUrlError(
            f"article URL path contains an invalid percent escape: {original_url!r}"
        )
    encoded_path = quote(path or "/", safe="/%:@!$&'()*+,;=-._~")

    def normalize_escape(match: re.Match[str]) -> str:
        byte_value = int(match.group(1), 16)
        character = chr(byte_value)
        if character in _UNRESERVED_CHARACTERS:
            return character
        return f"%{match.group(1).upper()}"

    normalized_path = _PERCENT_ESCAPE.sub(normalize_escape, encoded_path)
    if normalized_path != "/":
        return normalized_path.rstrip("/") or "/"
    return normalized_path


def normalize_url(url: str) -> str:
    """Canonicalize one absolute HTTP(S) URL without changing its resource semantics."""
    if not isinstance(url, str):
        raise TypeError(f"url must be str, got {type(url).__name__}")

    stripped_url = url.strip()
    if not stripped_url:
        raise InvalidArticleUrlError("article URL must not be empty")
    if any(character.isspace() for character in stripped_url):
        raise InvalidArticleUrlError(f"article URL must not contain whitespace: {stripped_url!r}")

    parsed = urlsplit(stripped_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise InvalidArticleUrlError(
            f"article URL scheme must be http or https, got {parsed.scheme!r}: {stripped_url!r}"
        )
    if parsed.hostname is None:
        raise InvalidArticleUrlError(f"article URL must include a hostname: {stripped_url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidArticleUrlError(f"article URL must not contain credentials: {stripped_url!r}")

    hostname = _normalize_hostname(parsed.hostname, stripped_url)
    try:
        port = parsed.port
    except ValueError as error:
        raise InvalidArticleUrlError(
            f"article URL contains an invalid port: {stripped_url!r}"
        ) from error

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = _normalize_path(parsed.path, stripped_url)

    query_items = tuple(
        sorted(
            (name, value)
            for name, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_tracking_parameter(name)
        )
    )
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def calculate_url_sha256(url: str) -> str:
    """Return the de-duplication digest for one normalized article URL."""
    return calculate_sha256(normalize_url(url))
