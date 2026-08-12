"""PostgreSQL persistence and exact media coverage for monitored companies."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.contracts import (
    CompaniesResponse,
    CompanyCoverageItem,
    CompanyCoverageResponse,
    CompanyCreateRequest,
    CompanyItem,
    MatchableCompany,
)
from app.companies.coverage import (
    build_evidence_contexts,
    calculate_captured_text_sha256,
    calculate_evidence_revision_sha256,
    combine_article_text,
    unique_matched_aliases,
)
from app.companies.errors import CompanyAliasConflictError, CompanyNotFoundError
from app.companies.identity import prepare_company_identity, reject_owned_company_names
from app.companies.models import CompanyAliasRecord, CompanyRecord
from app.media.collection.aliases import find_company_alias_matches
from app.media.models import MediaArticleRecord
from app.media.repository import (
    article_projection,
    article_summary,
    escaped_ilike_contains_pattern,
    representative_topic_subquery,
)

COVERAGE_CANDIDATE_BATCH_SIZE = 250
COVERAGE_CONTEXT_RADIUS = 120


@dataclass(frozen=True, slots=True)
class PersistedCompanyIdentity:
    """Public company item paired with its complete persisted matching identity."""

    item: CompanyItem
    matchable: MatchableCompany


def _company_item(
    company: CompanyRecord,
    aliases: tuple[CompanyAliasRecord, ...],
) -> CompanyItem:
    canonical_aliases = tuple(alias for alias in aliases if alias.is_canonical)
    if len(canonical_aliases) != 1:
        raise RuntimeError(
            f"company {company.id} must own exactly one canonical match name; "
            f"found {len(canonical_aliases)}"
        )
    canonical_alias = canonical_aliases[0]
    if canonical_alias.value != company.canonical_name:
        raise RuntimeError(
            f"company {company.id} canonical name does not match its canonical alias row"
        )
    return CompanyItem(
        id=company.id,
        canonical_name=company.canonical_name,
        aliases=tuple(alias.value for alias in aliases if not alias.is_canonical),
        created_at=company.created_at,
    )


async def _alias_owners(
    session: AsyncSession,
    normalized_names: tuple[str, ...],
) -> dict[str, UUID]:
    if not normalized_names:
        return {}
    rows = (
        await session.execute(
            select(
                CompanyAliasRecord.normalized_value,
                CompanyAliasRecord.company_id,
            ).where(CompanyAliasRecord.normalized_value.in_(normalized_names))
        )
    ).all()
    return {str(row.normalized_value): row.company_id for row in rows}


async def create_company(
    session: AsyncSession,
    request: CompanyCreateRequest,
) -> CompanyItem:
    """Persist one company after enforcing global normalized-name ownership."""
    identity = prepare_company_identity(request)
    normalized_names = tuple(name.normalized_value for name in identity.names)
    reject_owned_company_names(identity, await _alias_owners(session, normalized_names))

    company_id = uuid4()
    created_at = datetime.now(UTC)
    company = CompanyRecord(
        id=company_id,
        canonical_name=identity.canonical_name,
        created_at=created_at,
    )
    session.add(company)
    await session.flush()

    alias_values = [
        {
            "normalized_value": name.normalized_value,
            "company_id": company_id,
            "value": name.value,
            "is_canonical": name.is_canonical,
            "position": name.position,
        }
        for name in identity.names
    ]
    statement = (
        insert(CompanyAliasRecord)
        .values(alias_values)
        .on_conflict_do_nothing(index_elements=[CompanyAliasRecord.normalized_value])
        .returning(CompanyAliasRecord.normalized_value)
    )
    inserted_names = tuple((await session.execute(statement)).scalars())
    if len(inserted_names) != len(identity.names):
        await session.rollback()
        reject_owned_company_names(identity, await _alias_owners(session, normalized_names))
        raise CompanyAliasConflictError(
            "one or more company match names became unavailable during creation; retry "
            "with aliases that are not owned by another company"
        )

    await session.commit()
    return CompanyItem(
        id=company_id,
        canonical_name=identity.canonical_name,
        aliases=identity.aliases,
        created_at=created_at,
    )


async def list_companies(session: AsyncSession) -> CompaniesResponse:
    """List all monitored companies and their user-visible aliases."""
    companies = tuple(
        (
            await session.execute(
                select(CompanyRecord).order_by(
                    CompanyRecord.created_at.desc(),
                    CompanyRecord.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not companies:
        return CompaniesResponse(items=(), total=0)

    company_ids = tuple(company.id for company in companies)
    alias_rows = tuple(
        (
            await session.execute(
                select(CompanyAliasRecord)
                .where(CompanyAliasRecord.company_id.in_(company_ids))
                .order_by(CompanyAliasRecord.company_id, CompanyAliasRecord.position)
            )
        )
        .scalars()
        .all()
    )
    aliases_by_company: dict[UUID, list[CompanyAliasRecord]] = {
        company_id: [] for company_id in company_ids
    }
    for alias in alias_rows:
        aliases_by_company[alias.company_id].append(alias)
    items = tuple(
        _company_item(company, tuple(aliases_by_company[company.id])) for company in companies
    )
    return CompaniesResponse(items=items, total=len(items))


async def load_company_identity(
    session: AsyncSession,
    company_id: UUID,
) -> PersistedCompanyIdentity:
    """Load one company or raise an explicit not-found domain error."""
    company = await session.scalar(select(CompanyRecord).where(CompanyRecord.id == company_id))
    if company is None:
        raise CompanyNotFoundError(f"monitored company {company_id} was not found")
    aliases = tuple(
        (
            await session.execute(
                select(CompanyAliasRecord)
                .where(CompanyAliasRecord.company_id == company_id)
                .order_by(CompanyAliasRecord.position)
            )
        )
        .scalars()
        .all()
    )
    item = _company_item(company, aliases)
    return PersistedCompanyIdentity(
        item=item,
        matchable=MatchableCompany(
            company_id=str(company.id),
            names=tuple(alias.value for alias in aliases),
        ),
    )


def company_candidate_condition(names: tuple[str, ...]) -> ColumnElement[bool]:
    """Build escaped title/content ILIKE candidates for exact Python matching."""
    if not names:
        raise ValueError("names must contain at least one company match name")
    candidate_conditions: list[ColumnElement[bool]] = []
    for name in names:
        pattern = escaped_ilike_contains_pattern(name)
        candidate_conditions.extend(
            (
                MediaArticleRecord.title.ilike(pattern, escape="\\"),
                MediaArticleRecord.content.ilike(pattern, escape="\\"),
            )
        )
    return or_(*candidate_conditions)


async def get_company_coverage(
    session: AsyncSession,
    company_id: UUID,
    page: int,
    page_size: int,
) -> CompanyCoverageResponse:
    """Stream all SQL candidates to return an exact, memory-bounded coverage page.

    SQL ILIKE only reduces the candidate set. Every candidate is checked with the
    shared boundary/overlap matcher. The stream is fully consumed so totals and
    distinct counts always describe exact matches; only the requested page retains
    article bodies long enough to construct contexts.
    """
    identity = await load_company_identity(session, company_id)
    representative_topic = representative_topic_subquery()
    statement = (
        article_projection(representative_topic)
        .add_columns(
            MediaArticleRecord.source_id.label("coverage_source_id"),
            MediaArticleRecord.content.label("coverage_content"),
            MediaArticleRecord.summary.label("coverage_summary"),
            MediaArticleRecord.crawled_at.label("coverage_crawled_at"),
        )
        .where(company_candidate_condition(identity.matchable.names))
        .order_by(MediaArticleRecord.published_at.desc(), MediaArticleRecord.id.desc())
        .execution_options(yield_per=COVERAGE_CANDIDATE_BATCH_SIZE)
    )
    result = await session.stream(statement)

    page_start = (page - 1) * page_size
    page_end = page_start + page_size
    total_matching_articles = 0
    source_ids: set[UUID] = set()
    country_codes: set[str] = set()
    topic_ids: set[UUID] = set()
    items: list[CompanyCoverageItem] = []

    async for row in result:
        combined_text = combine_article_text(row.title, row.coverage_content)
        matches = find_company_alias_matches(combined_text, (identity.matchable,))
        if not matches:
            continue

        exact_index = total_matching_articles
        total_matching_articles += 1
        source_ids.add(row.coverage_source_id)
        if row.country_code is not None:
            country_codes.add(str(row.country_code))
        if row.topic_id is not None:
            topic_ids.add(row.topic_id)

        if page_start <= exact_index < page_end:
            items.append(
                CompanyCoverageItem(
                    article=article_summary(row),
                    captured_text_sha256=calculate_captured_text_sha256(
                        row.title,
                        row.coverage_content,
                    ),
                    evidence_revision_sha256=calculate_evidence_revision_sha256(
                        row.title,
                        row.coverage_content,
                        row.coverage_summary,
                        row.original_url,
                        row.published_at,
                        row.coverage_crawled_at,
                        row.country_code,
                        row.coverage_source_id,
                        row.source_name,
                    ),
                    matched_aliases=unique_matched_aliases(matches),
                    evidence_contexts=build_evidence_contexts(
                        combined_text,
                        matches,
                        COVERAGE_CONTEXT_RADIUS,
                    ),
                )
            )

    return CompanyCoverageResponse(
        company=identity.item,
        total_matching_articles=total_matching_articles,
        source_count=len(source_ids),
        country_count=len(country_codes),
        topic_count=len(topic_ids),
        items=tuple(items),
        page=page,
        page_size=page_size,
    )
