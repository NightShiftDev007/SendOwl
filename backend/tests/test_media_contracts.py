"""Media query validation and unique-article projection contracts."""

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.media import (
    create_media_router,
    normalize_media_search_query,
    require_media_session,
    require_media_source_evidence_session,
)
from app.media.contracts import (
    MediaArticleSummary,
    MediaSourceEvidenceResponse,
    MediaTopicsResponse,
)
from app.media.errors import MediaSourceEvidencePageOutOfRangeError, MediaSourceNotFoundError
from app.media.models import MediaArticleRecord
from app.media.repository import (
    UNCLASSIFIED_TOPIC,
    MediaArticleFilters,
    _article_filter_conditions,
    _classified_country_topic_counts,
    _classified_hot_topics,
    article_projection,
    representative_topic_subquery,
)


def _validation_client() -> TestClient:
    application = FastAPI()
    application.include_router(create_media_router())

    async def unused_session():
        yield object()

    application.dependency_overrides[require_media_session] = unused_session
    application.dependency_overrides[require_media_source_evidence_session] = unused_session
    return TestClient(application)


def _valid_article_values() -> dict[str, object]:
    return {
        "id": uuid4(),
        "title": "企业发布季度经营数据",
        "source_name": "Example News",
        "published_at": datetime.now(UTC),
        "excerpt": "可核验的报道摘录",
        "original_url": "https://example.com/articles/1",
        "country_code": "CN",
        "topic_id": uuid4(),
        "topic": "季度业绩",
        "evidence_revision_sha256": "a" * 64,
    }


def test_article_projection_filters_duplicates_and_truncates_summary_excerpt() -> None:
    representative_topic = representative_topic_subquery()
    statement = article_projection(representative_topic)
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()

    assert "media_articles.is_duplicate is false" in sql
    assert "substr(media_articles.summary" in sql
    assert "topic_id" in sql


def test_overview_topic_aggregates_exclude_unclassified_and_duplicate_articles() -> None:
    cutoff = datetime(2026, 8, 11, tzinfo=UTC)
    representative_topic = representative_topic_subquery()
    statements = (
        select(_classified_country_topic_counts(representative_topic, cutoff)),
        _classified_hot_topics(representative_topic, cutoff),
    )

    for statement in statements:
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        article_join = sql[sql.rfind("from media_articles") :]

        assert " join " in article_join
        assert "left outer join" not in article_join
        assert "media_articles.is_duplicate is false" in sql
        assert UNCLASSIFIED_TOPIC not in sql


def test_article_filter_uses_stable_topic_uuid_instead_of_display_name() -> None:
    topic_id = uuid4()
    representative_topic = representative_topic_subquery()
    conditions = _article_filter_conditions(
        MediaArticleFilters(q=None, country=None, topic_id=topic_id),
        representative_topic,
    )
    statement = (
        select(MediaArticleRecord.id)
        .outerjoin(
            representative_topic,
            representative_topic.c.article_id == MediaArticleRecord.id,
        )
        .where(*conditions)
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "topic_id" in sql
    assert str(topic_id) in sql
    assert "media_articles.is_duplicate is false" in sql


def test_article_summary_accepts_explicit_unclassified_identity() -> None:
    values = _valid_article_values()
    values.update({"topic_id": None, "topic": "未归类"})

    article = MediaArticleSummary.model_validate(values, strict=True)

    assert article.topic_id is None
    assert article.topic == "未归类"


def test_article_summary_rejects_excerpts_beyond_public_limit() -> None:
    values = _valid_article_values()
    values["excerpt"] = "摘" * 281

    with pytest.raises(ValidationError, match="280"):
        MediaArticleSummary.model_validate(values, strict=True)


def test_topics_response_requires_explicit_pagination_metadata() -> None:
    with pytest.raises(ValidationError):
        MediaTopicsResponse.model_validate({"items": ()}, strict=True)


def test_source_evidence_response_reuses_article_summary_without_full_content() -> None:
    source_id = uuid4()
    article = MediaArticleSummary.model_validate(_valid_article_values(), strict=True)
    response = MediaSourceEvidenceResponse.model_validate(
        {
            "source": {
                "id": source_id,
                "name": "Example News",
                "country_code": "CN",
                "homepage_url": "https://example.com",
                "media_type": "online",
                "language": "zh",
                "status": "active",
                "last_success_at": datetime.now(UTC),
            },
            "article_total": 1,
            "first_published_at": article.published_at,
            "latest_published_at": article.published_at,
            "items": (article,),
            "page": 1,
            "page_size": 20,
            "total": 1,
            "observed_at": datetime.now(UTC),
        },
        strict=True,
    )

    assert response.items == (article,)
    assert "content" not in response.model_dump(mode="json")["items"][0]


def test_source_evidence_projection_is_source_local_unique_and_newest_first() -> None:
    source_id = uuid4()
    representative_topic = representative_topic_subquery()
    statement = (
        article_projection(representative_topic)
        .where(MediaArticleRecord.source_id == source_id)
        .order_by(MediaArticleRecord.published_at.desc(), MediaArticleRecord.id.desc())
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "media_articles.source_id" in sql
    assert "media_articles.is_duplicate is false" in sql
    assert "media_articles.published_at desc" in sql
    assert "media_articles.id desc" in sql


@pytest.mark.parametrize(
    ("query", "expected_detail"),
    (
        (" ", "between 2 and 100"),
        ("a", "between 2 and 100"),
        ("a" * 101, "between 2 and 100"),
    ),
)
def test_search_query_rejects_invalid_length_after_trimming(
    query: str,
    expected_detail: str,
) -> None:
    with pytest.raises(HTTPException, match=expected_detail):
        normalize_media_search_query(query)


def test_search_query_is_trimmed_only_after_validation_boundary() -> None:
    assert normalize_media_search_query("  华为  ") == "华为"
    assert normalize_media_search_query(None) is None


@pytest.mark.parametrize(
    "path",
    (
        "/api/v2/media/articles?country=C1",
        "/api/v2/media/articles?country=中国",
        "/api/v2/media/articles?topic_id=not-a-uuid",
        "/api/v2/media/articles?topic=名称不是身份",
        "/api/v2/media/topics?page_size=101",
    ),
)
def test_media_query_boundary_returns_422_for_invalid_identity_or_pagination(path: str) -> None:
    response = _validation_client().get(path)

    assert response.status_code == 422


def test_source_evidence_query_boundary_rejects_ambiguous_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = uuid4()
    calls: list[tuple[int, int]] = []

    async def fake_source_evidence(
        session: object,
        received_source_id: object,
        page: int,
        page_size: int,
    ) -> MediaSourceEvidenceResponse:
        assert session is not None and received_source_id == source_id
        calls.append((page, page_size))
        return MediaSourceEvidenceResponse.model_validate(
            {
                "source": {
                    "id": source_id,
                    "name": "Example News",
                    "country_code": "CN",
                    "homepage_url": "https://example.com",
                    "media_type": "online",
                    "language": "zh",
                    "status": "active",
                    "last_success_at": None,
                },
                "article_total": 0,
                "first_published_at": None,
                "latest_published_at": None,
                "items": (),
                "page": page,
                "page_size": page_size,
                "total": 0,
                "observed_at": datetime.now(UTC),
            },
            strict=True,
        )

    monkeypatch.setattr("app.api.media.get_source_evidence", fake_source_evidence)
    client = _validation_client()

    response = client.get(f"/api/v2/media/sources/{source_id}/evidence?page=2&page_size=7")
    assert response.status_code == 200
    assert calls == [(2, 7)]
    repeated_page = client.get(f"/api/v2/media/sources/{source_id}/evidence?page=1&page=2")
    unknown_field = client.get(f"/api/v2/media/sources/{source_id}/evidence?topic_id={uuid4()}")
    assert repeated_page.status_code == 422
    assert unknown_field.status_code == 422


@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    (
        (MediaSourceNotFoundError, 404),
        (MediaSourceEvidencePageOutOfRangeError, 422),
    ),
)
def test_source_evidence_translates_repository_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[LookupError] | type[ValueError],
    expected_status: int,
) -> None:
    source_id = uuid4()

    async def failing_source_evidence(
        session: object,
        received_source_id: object,
        page: int,
        page_size: int,
    ) -> MediaSourceEvidenceResponse:
        assert (
            session is not None
            and received_source_id == source_id
            and page == 1
            and page_size == 20
        )
        raise error_type("source evidence error")

    monkeypatch.setattr("app.api.media.get_source_evidence", failing_source_evidence)
    response = _validation_client().get(f"/api/v2/media/sources/{source_id}/evidence")

    assert response.status_code == expected_status


def test_source_evidence_read_starts_repeatable_read_snapshot_before_repository_query() -> None:
    source = inspect.getsource(require_media_source_evidence_session)

    assert source.index("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY") < source.index(
        "yield session"
    )
