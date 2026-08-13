"""Media query validation and unique-article projection contracts."""

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
)
from app.media.contracts import MediaArticleSummary, MediaTopicsResponse
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
