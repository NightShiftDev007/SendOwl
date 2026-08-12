"""Pure monitored-company identity preparation and conflict semantics."""

from uuid import UUID

import pytest

from app.companies.contracts import CompanyCreateRequest
from app.companies.errors import CompanyAliasConflictError
from app.companies.identity import prepare_company_identity, reject_owned_company_names


def test_company_identity_trims_and_casefold_deduplicates_names() -> None:
    request = CompanyCreateRequest(
        canonical_name=" OpenAI ",
        aliases=("openai", " 开放人工智能 ", "OPENAI"),
    )

    identity = prepare_company_identity(request)

    assert identity.canonical_name == "OpenAI"
    assert identity.aliases == ("开放人工智能",)
    assert tuple(name.normalized_value for name in identity.names) == (
        "openai",
        "开放人工智能",
    )
    assert tuple(name.is_canonical for name in identity.names) == (True, False)


def test_company_create_request_accepts_the_json_alias_array_shape() -> None:
    request = CompanyCreateRequest.model_validate(
        {"canonical_name": "华为", "aliases": ["Huawei"]},
        strict=True,
    )

    assert request.aliases == ("Huawei",)


def test_company_identity_rejects_a_globally_owned_normalized_name() -> None:
    request = CompanyCreateRequest(canonical_name="OpenAI", aliases=("开放人工智能",))
    identity = prepare_company_identity(request)
    owner_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    with pytest.raises(
        CompanyAliasConflictError,
        match="already owned by company aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    ):
        reject_owned_company_names(identity, {"openai": owner_id})
