"""Pure schema and importer contract tests that do not require PostgreSQL."""

import pytest

from app.database import ApplicationBase
from app.media import models as media_models
from app.media import sync_models as media_sync_models
from app.media.import_agendascope import ImportConfigurationError, load_import_settings

del media_models, media_sync_models


def test_media_schema_contains_explicit_read_model_tables() -> None:
    assert {
        "media_sources",
        "media_articles",
        "media_topics",
        "media_topic_articles",
        "media_topic_snapshots",
        "media_first_utterances",
        "media_propagation_events",
        "media_propagation_edges",
        "media_sync_runs",
        "media_sync_run_tables",
    }.issubset(ApplicationBase.metadata.tables)
    article_columns = set(ApplicationBase.metadata.tables["media_articles"].columns.keys())
    topic_columns = set(ApplicationBase.metadata.tables["media_topics"].columns.keys())
    assert "embedding" not in article_columns
    assert "centroid" not in topic_columns


def test_importer_requires_both_explicit_database_urls() -> None:
    with pytest.raises(ImportConfigurationError, match="AGENDASCOPE_DATABASE_URL"):
        load_import_settings({"DATABASE_URL": "postgresql://app:secret@db:5432/adc"})


def test_importer_rejects_using_the_target_as_its_source() -> None:
    database_url = "postgresql://app:secret@db:5432/adc"
    with pytest.raises(ImportConfigurationError, match="must be different"):
        load_import_settings(
            {
                "AGENDASCOPE_DATABASE_URL": database_url,
                "DATABASE_URL": database_url,
            }
        )
