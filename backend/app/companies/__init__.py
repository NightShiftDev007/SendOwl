"""Company-identity domain contracts."""

from app.companies.contracts import (
    CompaniesResponse,
    CompanyAlias,
    CompanyAliasMatch,
    CompanyCoverageResponse,
    CompanyCreateRequest,
    CompanyItem,
    CompanyMention,
    CompanyProfile,
    MatchableCompany,
)

__all__ = [
    "CompaniesResponse",
    "CompanyAlias",
    "CompanyAliasMatch",
    "CompanyCoverageResponse",
    "CompanyCreateRequest",
    "CompanyItem",
    "CompanyMention",
    "CompanyProfile",
    "MatchableCompany",
]
