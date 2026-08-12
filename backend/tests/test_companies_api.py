"""Company API availability and strict HTTP behavior without external services."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.companies.contracts import CompanyCreateRequest
from app.config import load_runtime_settings
from app.main import create_app


def test_company_endpoints_return_explicit_503_without_database_configuration() -> None:
    client = TestClient(create_app(load_runtime_settings({})))

    list_response = client.get("/api/v2/companies")
    create_response = client.post(
        "/api/v2/companies",
        json={"canonical_name": "示例企业", "aliases": ["示例"]},
    )
    coverage_response = client.get(f"/api/v2/companies/{uuid4()}/coverage")

    expected = {"detail": "Company data is unavailable because DATABASE_URL is not configured"}
    assert list_response.status_code == 503
    assert list_response.json() == expected
    assert create_response.status_code == 503
    assert create_response.json() == expected
    assert coverage_response.status_code == 503
    assert coverage_response.json() == expected


def test_company_create_request_contract_rejects_empty_names() -> None:
    with pytest.raises(ValidationError):
        CompanyCreateRequest(canonical_name="合法企业", aliases=("  ",))
