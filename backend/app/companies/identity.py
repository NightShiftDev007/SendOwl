"""Pure canonical-name and alias preparation for persisted company identities."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from app.companies.contracts import CompanyCreateRequest
from app.companies.errors import CompanyAliasConflictError


@dataclass(frozen=True, slots=True)
class PreparedCompanyName:
    """One normalized persisted name with a stable display order."""

    value: str
    normalized_value: str
    is_canonical: bool
    position: int


@dataclass(frozen=True, slots=True)
class PreparedCompanyIdentity:
    """Canonical company name and de-duplicated matching names."""

    canonical_name: str
    aliases: tuple[str, ...]
    names: tuple[PreparedCompanyName, ...]


def normalize_company_name(value: str) -> str:
    """Normalize one already validated company name for identity comparison."""
    if not isinstance(value, str):
        raise TypeError(f"value must be str, got {type(value).__name__}")
    stripped_value = value.strip()
    if not stripped_value:
        raise ValueError("company name must not be empty")
    return stripped_value.casefold()


def prepare_company_identity(request: CompanyCreateRequest) -> PreparedCompanyIdentity:
    """Trim and casefold-de-duplicate one create request without mutating it."""
    if not isinstance(request, CompanyCreateRequest):
        raise TypeError(f"request must be CompanyCreateRequest, got {type(request).__name__}")

    canonical_name = request.canonical_name.strip()
    raw_names = (canonical_name, *request.aliases)
    seen_normalized_names: set[str] = set()
    names: list[PreparedCompanyName] = []
    aliases: list[str] = []
    for raw_name in raw_names:
        value = raw_name.strip()
        normalized_value = normalize_company_name(value)
        if normalized_value in seen_normalized_names:
            continue
        seen_normalized_names.add(normalized_value)
        is_canonical = not names
        position = len(names)
        names.append(
            PreparedCompanyName(
                value=value,
                normalized_value=normalized_value,
                is_canonical=is_canonical,
                position=position,
            )
        )
        if not is_canonical:
            aliases.append(value)
    return PreparedCompanyIdentity(
        canonical_name=canonical_name,
        aliases=tuple(aliases),
        names=tuple(names),
    )


def reject_owned_company_names(
    identity: PreparedCompanyIdentity,
    owner_by_normalized_name: Mapping[str, UUID],
) -> None:
    """Raise the first deterministic conflict found in global alias ownership."""
    if not isinstance(identity, PreparedCompanyIdentity):
        raise TypeError(f"identity must be PreparedCompanyIdentity, got {type(identity).__name__}")
    for name in identity.names:
        owner_id = owner_by_normalized_name.get(name.normalized_value)
        if owner_id is not None:
            raise CompanyAliasConflictError(
                f"company match name {name.value!r} is already owned by company {owner_id}"
            )
