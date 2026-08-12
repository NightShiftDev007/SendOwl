"""Deterministic company resolution and exact mention offsets."""

import pytest

from app.companies.contracts import CompanyAlias, CompanyProfile, MatchableCompany
from app.media.collection import (
    AmbiguousCompanyAliasError,
    AmbiguousCompanyMentionError,
    CompanyAliasMatchLimitError,
    find_company_alias_matches,
    find_company_alias_matches_bounded,
    find_company_mentions,
)


def _build_company(
    company_id: str,
    canonical_name: str,
    aliases: tuple[str, ...],
) -> CompanyProfile:
    return CompanyProfile(
        company_id=company_id,
        canonical_name=canonical_name,
        jurisdiction="CN",
        aliases=tuple(
            CompanyAlias(value=alias, language="zh", evidence_ids=("registry-001",))
            for alias in aliases
        ),
    )


def test_alias_matching_is_case_insensitive_for_latin_and_respects_latin_boundaries() -> None:
    company = _build_company("company-openai", "OpenAI", ("openai",))
    content = "OpenAI与openai合作；SuperOpenAI不匹配；OpenAI_Labs不匹配；OpenAI中国发布。"

    mentions = find_company_mentions(
        content=content,
        evidence_id="evidence-001",
        companies=(company,),
    )

    expected_starts = (
        content.index("OpenAI"),
        content.index("openai"),
        content.rindex("OpenAI"),
    )
    assert tuple(mention.start_offset for mention in mentions) == expected_starts
    assert tuple(mention.surface_form for mention in mentions) == ("OpenAI", "openai", "OpenAI")
    assert all(
        content[mention.start_offset : mention.end_offset] == mention.surface_form
        for mention in mentions
    )


def test_duplicate_and_overlapping_aliases_for_one_company_choose_longest_range() -> None:
    company = _build_company(
        "company-alibaba",
        "阿里巴巴集团",
        ("阿里巴巴", "阿里巴巴集团", "阿里"),
    )
    content = "阿里巴巴集团宣布组织升级。"

    mentions = find_company_mentions(
        content=content,
        evidence_id="evidence-001",
        companies=(company,),
    )

    assert len(mentions) == 1
    assert mentions[0].surface_form == "阿里巴巴集团"
    assert (mentions[0].start_offset, mentions[0].end_offset) == (0, len("阿里巴巴集团"))


def test_same_alias_for_different_companies_is_an_explicit_error() -> None:
    first_company = _build_company("company-first", "甲公司", ("ACME",))
    second_company = _build_company("company-second", "乙公司", ("acme",))

    with pytest.raises(
        AmbiguousCompanyAliasError,
        match="resolves to multiple companies: company-first, company-second",
    ):
        find_company_mentions(
            content="ACME发布公告。",
            evidence_id="evidence-001",
            companies=(first_company, second_company),
        )


def test_overlapping_aliases_for_different_companies_are_an_explicit_error() -> None:
    first_company = _build_company("company-alpha-bank", "Alpha Bank", ())
    second_company = _build_company("company-bank", "Bank", ())

    with pytest.raises(AmbiguousCompanyMentionError, match="overlapping company aliases"):
        find_company_mentions(
            content="Alpha Bank announced its results.",
            evidence_id="evidence-001",
            companies=(first_company, second_company),
        )


def test_minimal_matchable_company_reuses_exact_matching_without_fake_profile_fields() -> None:
    company = MatchableCompany(
        company_id="company-openai",
        names=("OpenAI", "开放人工智能"),
    )
    content = "开放人工智能（OpenAI）发布新模型。"

    matches = find_company_alias_matches(content, (company,))

    assert tuple(match.alias for match in matches) == ("开放人工智能", "OpenAI")
    assert tuple(match.surface_form for match in matches) == ("开放人工智能", "OpenAI")


def test_bounded_alias_matching_preserves_order_and_stops_at_first_excess_match() -> None:
    company = MatchableCompany(company_id="company-acme", names=("Acme",))
    content = " ".join("Acme" for _index in range(5000))

    with pytest.raises(CompanyAliasMatchLimitError) as raised:
        find_company_alias_matches_bounded(content, (company,), max_matches=200)

    assert raised.value.observed_matches == 201
    assert raised.value.limit == 200


@pytest.mark.parametrize(
    ("names", "content"),
    (
        (("I", "ı"), "I ı"),
        (("ſ", "S"), "s ſ"),
        (("K", "K"), "K K"),
        (("阿里", "阿里巴巴", "阿里巴巴集团"), "阿里巴巴集团与阿里"),
        (("OpenAI", "openai"), "OpenAI 与 openai"),
    ),
)
def test_bounded_alias_matching_equals_eager_matching_when_limit_is_not_reached(
    names: tuple[str, ...],
    content: str,
) -> None:
    company = MatchableCompany(company_id="company-example", names=names)

    eager = find_company_alias_matches(content, (company,))
    bounded = find_company_alias_matches_bounded(content, (company,), max_matches=100)

    assert bounded == eager
