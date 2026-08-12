"""Deterministic company-alias matching with exact, non-overlapping offsets."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from heapq import heappop, heappush

from pydantic import TypeAdapter

from app.companies.contracts import (
    CompanyAliasMatch,
    CompanyMention,
    CompanyProfile,
    MatchableCompany,
)
from app.media.collection.errors import (
    AmbiguousCompanyAliasError,
    AmbiguousCompanyMentionError,
    CompanyAliasMatchLimitError,
    DuplicateCompanyProfileError,
)
from app.shared.contracts import Identifier

_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)
_ASCII_WORD_CHARACTER = re.compile(r"[A-Za-z0-9_]")


@dataclass(frozen=True, slots=True)
class _AliasOwner:
    alias: str
    company_id: str


@dataclass(frozen=True, slots=True)
class _MentionCandidate:
    company_id: str
    alias: str
    start_offset: int
    end_offset: int
    surface_form: str


def _candidate_preference_key(candidate: _MentionCandidate) -> tuple[int, int, str, str]:
    """Return one total order shared by eager and bounded overlap resolution."""
    return (
        -(candidate.end_offset - candidate.start_offset),
        candidate.start_offset,
        candidate.alias.casefold(),
        candidate.alias,
    )


def _alias_key(alias: str) -> str:
    return alias.strip().casefold()


def _build_alias_owners(companies: tuple[MatchableCompany, ...]) -> tuple[_AliasOwner, ...]:
    company_ids: set[str] = set()
    company_id_by_alias_key: dict[str, str] = {}
    seen_owners: set[tuple[str, str]] = set()
    owners: list[_AliasOwner] = []
    for company in companies:
        if company.company_id in company_ids:
            raise DuplicateCompanyProfileError(
                f"company profile {company.company_id!r} was supplied more than once"
            )
        company_ids.add(company.company_id)

        for alias in company.names:
            key = _alias_key(alias)
            existing_company_id = company_id_by_alias_key.get(key)
            if existing_company_id is not None and existing_company_id != company.company_id:
                conflicting_ids = sorted((existing_company_id, company.company_id))
                raise AmbiguousCompanyAliasError(
                    f"company alias {alias.strip()!r} resolves to multiple companies: "
                    f"{', '.join(conflicting_ids)}"
                )
            company_id_by_alias_key[key] = company.company_id
            owner_key = (company.company_id, alias.strip())
            if owner_key in seen_owners:
                continue
            seen_owners.add(owner_key)
            owners.append(_AliasOwner(alias=alias.strip(), company_id=company.company_id))
    return tuple(owners)


def _compile_alias_pattern(alias: str) -> re.Pattern[str]:
    escaped_alias = re.escape(alias)
    left_boundary = r"(?<![A-Za-z0-9_])" if _ASCII_WORD_CHARACTER.fullmatch(alias[0]) else ""
    right_boundary = r"(?![A-Za-z0-9_])" if _ASCII_WORD_CHARACTER.fullmatch(alias[-1]) else ""
    return re.compile(f"{left_boundary}{escaped_alias}{right_boundary}", re.IGNORECASE)


def _collect_candidates(
    content: str,
    owners: tuple[_AliasOwner, ...],
) -> tuple[_MentionCandidate, ...]:
    candidates: dict[tuple[str, int, int], _MentionCandidate] = {}
    for owner in owners:
        pattern = _compile_alias_pattern(owner.alias)
        for match in pattern.finditer(content):
            key = (owner.company_id, match.start(), match.end())
            candidate = _MentionCandidate(
                company_id=owner.company_id,
                alias=owner.alias,
                start_offset=match.start(),
                end_offset=match.end(),
                surface_form=content[match.start() : match.end()],
            )
            existing = candidates.get(key)
            if existing is None or _candidate_preference_key(candidate) < _candidate_preference_key(
                existing
            ):
                candidates[key] = candidate
    return tuple(
        sorted(
            candidates.values(),
            key=lambda candidate: (
                candidate.start_offset,
                -(candidate.end_offset - candidate.start_offset),
                candidate.company_id,
                candidate.alias.casefold(),
            ),
        )
    )


def _format_ambiguous_candidates(candidates: tuple[_MentionCandidate, ...]) -> str:
    return "; ".join(
        (
            f"company={candidate.company_id}, surface={candidate.surface_form!r}, "
            f"range=[{candidate.start_offset},{candidate.end_offset})"
        )
        for candidate in candidates
    )


def _resolve_overlaps(
    candidates: tuple[_MentionCandidate, ...],
) -> tuple[_MentionCandidate, ...]:
    if not candidates:
        return ()

    groups: list[tuple[_MentionCandidate, ...]] = []
    current_group: list[_MentionCandidate] = [candidates[0]]
    current_end = candidates[0].end_offset
    for candidate in candidates[1:]:
        if candidate.start_offset < current_end:
            current_group.append(candidate)
            current_end = max(current_end, candidate.end_offset)
            continue
        groups.append(tuple(current_group))
        current_group = [candidate]
        current_end = candidate.end_offset
    groups.append(tuple(current_group))

    resolved: list[_MentionCandidate] = []
    for group in groups:
        company_ids = {candidate.company_id for candidate in group}
        if len(company_ids) > 1:
            raise AmbiguousCompanyMentionError(
                "overlapping company aliases resolve to different companies: "
                f"{_format_ambiguous_candidates(group)}"
            )
        selected = min(
            group,
            key=_candidate_preference_key,
        )
        resolved.append(selected)
    return tuple(resolved)


def _iter_candidates_in_resolution_order(
    content: str,
    owners: tuple[_AliasOwner, ...],
) -> Iterator[_MentionCandidate]:
    """Merge regex iterators without materializing every occurrence in the article."""
    iterators: list[Iterator[re.Match[str]]] = []
    heap: list[tuple[int, int, str, str, str, int, re.Match[str]]] = []
    for owner_index, owner in enumerate(owners):
        iterator = iter(_compile_alias_pattern(owner.alias).finditer(content))
        iterators.append(iterator)
        first_match = next(iterator, None)
        if first_match is None:
            continue
        heappush(
            heap,
            (
                first_match.start(),
                -(first_match.end() - first_match.start()),
                owner.company_id,
                owner.alias.casefold(),
                owner.alias,
                owner_index,
                first_match,
            ),
        )

    while heap:
        (
            _start,
            _negative_length,
            _company_id,
            _alias_key_value,
            _alias,
            owner_index,
            match,
        ) = heappop(heap)
        owner = owners[owner_index]
        yield _MentionCandidate(
            company_id=owner.company_id,
            alias=owner.alias,
            start_offset=match.start(),
            end_offset=match.end(),
            surface_form=content[match.start() : match.end()],
        )
        next_match = next(iterators[owner_index], None)
        if next_match is not None:
            heappush(
                heap,
                (
                    next_match.start(),
                    -(next_match.end() - next_match.start()),
                    owner.company_id,
                    owner.alias.casefold(),
                    owner.alias,
                    owner_index,
                    next_match,
                ),
            )


def _resolved_candidate(
    best_candidate: _MentionCandidate,
    company_samples: dict[str, _MentionCandidate],
) -> _MentionCandidate:
    if len(company_samples) > 1:
        raise AmbiguousCompanyMentionError(
            "overlapping company aliases resolve to different companies: "
            f"{_format_ambiguous_candidates(tuple(company_samples.values()))}"
        )
    return best_candidate


def _company_alias_match(candidate: _MentionCandidate) -> CompanyAliasMatch:
    return CompanyAliasMatch(
        company_id=candidate.company_id,
        alias=candidate.alias,
        surface_form=candidate.surface_form,
        start_offset=candidate.start_offset,
        end_offset=candidate.end_offset,
    )


def find_company_alias_matches_bounded(
    content: str,
    companies: tuple[MatchableCompany, ...],
    max_matches: int,
) -> tuple[CompanyAliasMatch, ...]:
    """Resolve matches lazily and stop immediately after the configured maximum."""
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    if not isinstance(companies, tuple) or any(
        not isinstance(company, MatchableCompany) for company in companies
    ):
        raise TypeError("companies must be a tuple of MatchableCompany values")
    if isinstance(max_matches, bool) or not isinstance(max_matches, int):
        raise TypeError("max_matches must be int")
    if max_matches < 1:
        raise ValueError(f"max_matches must be positive, got {max_matches}")

    owners = _build_alias_owners(companies)
    matches: list[CompanyAliasMatch] = []
    best_candidate: _MentionCandidate | None = None
    current_end = 0
    company_samples: dict[str, _MentionCandidate] = {}

    def append_resolved() -> None:
        if best_candidate is None:
            return
        matches.append(_company_alias_match(_resolved_candidate(best_candidate, company_samples)))
        if len(matches) > max_matches:
            raise CompanyAliasMatchLimitError(
                observed_matches=len(matches),
                limit=max_matches,
            )

    for candidate in _iter_candidates_in_resolution_order(content, owners):
        if best_candidate is not None and candidate.start_offset >= current_end:
            append_resolved()
            best_candidate = candidate
            current_end = candidate.end_offset
            company_samples = {candidate.company_id: candidate}
            continue
        if best_candidate is None:
            best_candidate = candidate
            current_end = candidate.end_offset
            company_samples = {candidate.company_id: candidate}
            continue
        current_end = max(current_end, candidate.end_offset)
        company_samples.setdefault(candidate.company_id, candidate)
        candidate_key = _candidate_preference_key(candidate)
        best_key = _candidate_preference_key(best_candidate)
        if candidate_key < best_key:
            best_candidate = candidate

    append_resolved()
    return tuple(matches)


def find_company_alias_matches(
    content: str,
    companies: tuple[MatchableCompany, ...],
) -> tuple[CompanyAliasMatch, ...]:
    """Resolve configured aliases to exact ranges using the shared overlap policy."""
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    if not isinstance(companies, tuple) or any(
        not isinstance(company, MatchableCompany) for company in companies
    ):
        raise TypeError("companies must be a tuple of MatchableCompany values")
    owners = _build_alias_owners(companies)
    candidates = _collect_candidates(content, owners)
    resolved = _resolve_overlaps(candidates)
    return tuple(
        CompanyAliasMatch(
            company_id=candidate.company_id,
            alias=candidate.alias,
            surface_form=candidate.surface_form,
            start_offset=candidate.start_offset,
            end_offset=candidate.end_offset,
        )
        for candidate in resolved
    )


def find_company_mentions(
    content: str,
    evidence_id: str,
    companies: tuple[CompanyProfile, ...],
) -> tuple[CompanyMention, ...]:
    """Resolve legacy evidence mentions through the minimal shared matching kernel."""
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    if not isinstance(companies, tuple) or any(
        not isinstance(company, CompanyProfile) for company in companies
    ):
        raise TypeError("companies must be a tuple of CompanyProfile values")
    validated_evidence_id = _IDENTIFIER_ADAPTER.validate_python(evidence_id, strict=True)
    matchable_companies = tuple(
        MatchableCompany(
            company_id=company.company_id,
            names=(company.canonical_name, *(alias.value for alias in company.aliases)),
        )
        for company in companies
    )
    matches = find_company_alias_matches(content, matchable_companies)
    return tuple(
        CompanyMention(
            company_id=match.company_id,
            evidence_id=validated_evidence_id,
            surface_form=match.surface_form,
            start_offset=match.start_offset,
            end_offset=match.end_offset,
        )
        for match in matches
    )
