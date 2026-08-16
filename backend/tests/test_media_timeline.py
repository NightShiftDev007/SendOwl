"""Topic timeline API, query semantics, and strict response contracts."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api import media as media_api
from app.api.media import require_media_session
from app.config import load_runtime_settings
from app.main import create_app
from app.media.contracts import (
    MediaTopicLatestCountry,
    MediaTopicTimelinePoint,
    MediaTopicTimelineResponse,
)
from app.media.errors import MediaTopicNotFoundError
from app.media.repository import (
    topic_latest_countries_statement,
    topic_timeline_points_statement,
)


def _timeline_response(topic_id: UUID, selected_country: str | None) -> MediaTopicTimelineResponse:
    started_at = datetime(2026, 8, 12, 1, tzinfo=UTC)
    return MediaTopicTimelineResponse(
        topic_id=topic_id,
        topic="可核验议题",
        selected_country=selected_country,
        points=(
            MediaTopicTimelinePoint(
                window_start=started_at,
                window_end=started_at + timedelta(days=1),
                granularity="hour",
                article_count=3,
                salience_score=1.25,
                salience_rank=2 if selected_country is not None else None,
            ),
        ),
        latest_countries=(
            MediaTopicLatestCountry(
                country_code="CN",
                window_start=started_at,
                window_end=started_at + timedelta(days=1),
                granularity="hour",
                article_count=3,
                salience_score=1.25,
                salience_rank=2,
            ),
        ),
        generated_at=datetime(2026, 8, 13, tzinfo=UTC),
        limitations=("Observed media coverage only.",),
    )


def _application_with_media_session() -> FastAPI:
    application = create_app(load_runtime_settings({}))

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[require_media_session] = session_override
    return application


def test_topic_timeline_forwards_normalized_iso_country_and_limit(monkeypatch) -> None:
    application = _application_with_media_session()
    topic_id = uuid4()
    expected = _timeline_response(topic_id, "CN")

    async def timeline(
        session: object,
        requested_topic_id: UUID,
        country: str | None,
        limit: int,
    ) -> MediaTopicTimelineResponse:
        assert session is not None
        assert requested_topic_id == topic_id
        assert country == "CN"
        assert limit == 24
        return expected

    monkeypatch.setattr(media_api, "get_topic_timeline", timeline)
    response = TestClient(application).get(
        f"/api/v2/media/topics/{topic_id}/timeline?country=cn&limit=24"
    )

    assert response.status_code == 200
    assert MediaTopicTimelineResponse.model_validate_json(response.content) == expected


def test_topic_timeline_maps_missing_topic_to_404(monkeypatch) -> None:
    application = _application_with_media_session()
    topic_id = uuid4()

    async def missing_topic(
        session: object,
        requested_topic_id: UUID,
        country: str | None,
        limit: int,
    ) -> MediaTopicTimelineResponse:
        assert session is not None
        assert (requested_topic_id, country, limit) == (topic_id, None, 96)
        raise MediaTopicNotFoundError(f"media topic {topic_id} does not exist")

    monkeypatch.setattr(media_api, "get_topic_timeline", missing_topic)
    response = TestClient(application).get(f"/api/v2/media/topics/{topic_id}/timeline")

    assert response.status_code == 404
    assert response.json() == {"detail": f"media topic {topic_id} does not exist"}


@pytest.mark.parametrize(
    "query",
    (
        "country=ZZ",
        "country=C1",
        "limit=1",
        "limit=501",
    ),
)
def test_topic_timeline_rejects_invalid_country_or_limit(query: str) -> None:
    application = _application_with_media_session()
    response = TestClient(application).get(f"/api/v2/media/topics/{uuid4()}/timeline?{query}")

    assert response.status_code == 422


def test_aggregated_timeline_sums_country_indexed_values_before_bounding() -> None:
    statement = topic_timeline_points_statement(uuid4(), None, 24)
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "sum(media_topic_snapshots.article_count)" in sql
    assert "sum(media_topic_snapshots.salience_score)" in sql
    assert "group by media_topic_snapshots.window_start" in sql
    assert "order by media_topic_snapshots.window_start desc" in sql
    assert "limit 24" in sql
    assert "order by anon_1.window_start asc" in sql
    assert "media_topic_snapshots.country_code =" not in sql


def test_country_timeline_preserves_snapshot_rank_without_cross_country_sum() -> None:
    statement = topic_timeline_points_statement(uuid4(), "CN", 18)
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "media_topic_snapshots.country_code = 'cn'" in sql
    assert "media_topic_snapshots.salience_rank" in sql
    assert "sum(media_topic_snapshots.article_count)" not in sql
    assert "limit 18" in sql


def test_latest_country_query_uses_each_country_latest_snapshot_then_salience_order() -> None:
    statement = topic_latest_countries_statement(uuid4())
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "row_number() over (partition by media_topic_snapshots.country_code" in sql
    assert "snapshot_recency = 1" in sql
    assert "salience_score desc" in sql
    assert "limit 12" in sql


def test_topic_timeline_rejects_nonfinite_or_negative_salience() -> None:
    started_at = datetime(2026, 8, 12, tzinfo=UTC)
    values = {
        "window_start": started_at,
        "window_end": started_at + timedelta(hours=1),
        "granularity": "hour",
        "article_count": 1,
        "salience_score": float("nan"),
        "salience_rank": 1,
    }

    with pytest.raises(ValidationError):
        MediaTopicTimelinePoint.model_validate(values, strict=True)

    values["salience_score"] = -0.01
    with pytest.raises(ValidationError):
        MediaTopicTimelinePoint.model_validate(values, strict=True)
