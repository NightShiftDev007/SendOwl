"""Application metadata contracts for company persistence."""

from app.companies import models as company_models
from app.database import ApplicationBase

del company_models


def test_company_schema_uses_application_metadata_and_global_alias_identity() -> None:
    assert {"companies", "company_aliases"}.issubset(ApplicationBase.metadata.tables)

    aliases = ApplicationBase.metadata.tables["company_aliases"]

    assert tuple(column.name for column in aliases.primary_key.columns) == ("normalized_value",)
    assert {foreign_key.target_fullname for foreign_key in aliases.foreign_keys} == {"companies.id"}
