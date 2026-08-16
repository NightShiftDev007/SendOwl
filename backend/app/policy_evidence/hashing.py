"""Canonical content addresses for immutable Policy evidence."""

from datetime import date
from hashlib import sha256

SOURCE_SCHEMA_VERSION = "policy-source/v1"
DOCUMENT_SCHEMA_VERSION = "policy-document/v1"
VERSION_SCHEMA_VERSION = "policy-document-version/v1"


def _digest(parts: tuple[str, ...]) -> str:
    if not parts or any("\x00" in part for part in parts):
        raise ValueError("policy digest parts must be non-empty and cannot contain NUL")
    return sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def calculate_policy_source_sha256(
    authority_name: str,
    jurisdiction_code: str,
    homepage_url: str,
) -> str:
    return _digest(
        (
            SOURCE_SCHEMA_VERSION,
            authority_name,
            jurisdiction_code,
            homepage_url,
        )
    )


def calculate_policy_document_sha256(
    source_sha256: str,
    canonical_identifier: str,
) -> str:
    return _digest((DOCUMENT_SCHEMA_VERSION, source_sha256, canonical_identifier))


def calculate_policy_version_sha256(
    document_sha256: str,
    title: str,
    original_url: str,
    language: str,
    publication_date: date,
    effective_from: date | None,
    effective_until: date | None,
    content_sha256: str,
) -> str:
    return _digest(
        (
            VERSION_SCHEMA_VERSION,
            document_sha256,
            title,
            original_url,
            language,
            publication_date.isoformat(),
            "" if effective_from is None else effective_from.isoformat(),
            "" if effective_until is None else effective_until.isoformat(),
            content_sha256,
        )
    )


def calculate_policy_content_sha256(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "calculate_policy_content_sha256",
    "calculate_policy_document_sha256",
    "calculate_policy_source_sha256",
    "calculate_policy_version_sha256",
]
