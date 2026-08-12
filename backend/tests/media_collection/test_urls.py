"""Stable URL and digest behavior for media collection."""

import pytest

from app.media.collection import (
    InvalidArticleUrlError,
    calculate_sha256,
    calculate_url_sha256,
    normalize_url,
)


def test_normalize_url_removes_tracking_and_stabilizes_equivalent_urls() -> None:
    first_url = (
        " HTTPS://Example.COM:443/news/company-update/"
        "?utm_source=wechat&b=2&a=1&fbclid=tracking#comments "
    )
    second_url = "https://example.com/news/company-update?a=1&b=2"

    assert normalize_url(first_url) == second_url
    assert calculate_url_sha256(first_url) == calculate_url_sha256(second_url)


def test_normalize_url_preserves_repeated_and_blank_business_parameters() -> None:
    url = "http://Example.com:80/search/?tag=b&empty=&tag=a&utm_medium=social"

    assert normalize_url(url) == "http://example.com/search?empty=&tag=a&tag=b"


def test_normalize_url_stabilizes_unicode_and_percent_encoded_paths() -> None:
    unicode_url = "https://例子.公司/企业/报道"
    encoded_url = "https://xn--fsqu00a.xn--55qx5d/%E4%BC%81%E4%B8%9A/%E6%8A%A5%E9%81%93"

    assert normalize_url(unicode_url) == encoded_url
    assert calculate_url_sha256(unicode_url) == calculate_url_sha256(encoded_url)


@pytest.mark.parametrize(
    "url, expected_message",
    [
        ("example.com/article", "scheme must be http or https"),
        ("ftp://example.com/article", "scheme must be http or https"),
        ("https:///article", "must include a hostname"),
        ("https://user:password@example.com/article", "must not contain credentials"),
        ("https://example.com:invalid/article", "invalid port"),
    ],
)
def test_normalize_url_rejects_noncanonical_external_identifiers(
    url: str,
    expected_message: str,
) -> None:
    with pytest.raises(InvalidArticleUrlError, match=expected_message):
        normalize_url(url)


def test_calculate_sha256_hashes_exact_unicode_content() -> None:
    assert calculate_sha256("企业报道") == (
        "786127b10eaa6c6c1106c42bbf7fe61862be7bfc411cc0962acd949abde6043b"
    )
    assert calculate_sha256("企业报道\n") != calculate_sha256("企业报道")
