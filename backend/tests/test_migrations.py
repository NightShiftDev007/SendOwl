"""Core migration-chain, schema ownership, and isolation checks."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.api.semantic_experiments import require_semantic_experiment_session
from app.config import load_runtime_settings
from app.database import normalize_async_database_url
from app.main import create_app
from app.populations.contracts import StoredPersonaProfile, StoredPersonaProvenance
from app.populations.hashing import calculate_cohort_sha256, calculate_persona_profile_sha256
from app.scenarios.contracts import Intervention, ScenarioSnapshotRef, ScenarioVariant
from app.scenarios.hashing import calculate_scenario_sha256, canonical_scenario_json
from app.semantic_experiments.contracts import FrozenSemanticVariant
from app.semantic_experiments.hashing import (
    PROMPT_SCHEMA_VERSION,
    calculate_semantic_experiment_sha256,
    calculate_semantic_trial_sha256,
)
from app.semantic_experiments.repository import get_semantic_experiment
from app.simulations.compiler import (
    derive_scenario_actor_bio,
    derive_scenario_actor_name,
    derive_scenario_actor_user_name,
)
from app.simulations.contracts import (
    CompiledPlatformSmokeInput,
    PlatformSmokePost,
    PlatformSmokeScenarioRef,
)
from app.simulations.hashing import (
    calculate_platform_smoke_input_sha256,
    canonical_platform_smoke_input_json,
)
from app.world_models.contracts import SnapshotEvidence
from app.world_models.hashing import calculate_snapshot_sha256, canonical_snapshot_json

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
REPOSITORY_DIRECTORY = BACKEND_DIRECTORY.parent
VERSIONS_DIRECTORY = BACKEND_DIRECTORY / "migrations" / "versions"
MIGRATION_FILE = VERSIONS_DIRECTORY / "20260812_core_0001_initial_schema.py"
WORLD_MODELS_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260812_core_0002_world_models.py"
SNAPSHOT_PROTECTION_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260812_core_0003_protect_world_snapshots.py"
)
SNAPSHOT_SEALING_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260812_core_0004_seal_world_snapshots.py"
SNAPSHOT_HARDENING_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260812_core_0005_harden_world_snapshot_sealing.py"
)
SCENARIOS_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260812_core_0006_immutable_scenarios.py"
SCENARIO_DEDUPLICATION_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260812_core_0007_deduplicate_scenario_specs.py"
)
PLATFORM_SMOKE_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260812_core_0008_oasis_platform_smoke_runs.py"
)
POPULATIONS_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260812_core_0009_matraix_persona_populations.py"
)
SEMANTIC_EXPERIMENTS_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260812_core_0010_semantic_experiments.py"
)
SEMANTIC_WORLD_GRAPHS_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260812_core_0011_semantic_world_graphs.py"
)
DECISION_THREADS_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260812_core_0012_decision_threads.py"
DECISION_REPORTS_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260812_core_0013_decision_reports.py"
REPORT_QUESTIONS_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260813_core_0014_report_questions.py"
REPORT_QUESTIONS_HARDENING_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260813_core_0015_harden_report_questions.py"
)
MATRAIX_SURVEYS_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260813_core_0016_matraix_surveys.py"
PERSONA_INTERVIEW_SESSIONS_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260813_core_0018_persona_interview_sessions.py"
)
MEDIA_PROPAGATION_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260813_core_0019_media_propagation.py"
MEDIA_SYNC_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260813_core_0020_media_sync_runs.py"
MATRAIX_CHAT_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260813_core_0021_matraix_chat.py"
MATRAIX_BATCH_REGISTRY_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260813_core_0022_matraix_batch_registry.py"
)
REPORT_QUESTION_THREADS_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260813_core_0023_report_question_threads.py"
)
MATRAIX_CHAT_MCP_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260813_core_0024_matraix_chat_mcp.py"
STRUCTURED_MEDIA_PROPAGATION_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260813_core_0025_structured_media_propagation.py"
)
CHAT_RETRY_LINEAGE_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260813_core_0026_chat_retry_lineage.py"
SURVEY_RETRY_LINEAGE_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260813_core_0027_survey_retry_lineage.py"
)
MEDIA_FIRST_UTTERANCES_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260813_core_0028_media_first_utterances.py"
)
GRAPH_PERSONA_COHORT_ORIGINS_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260814_core_0029_graph_persona_cohort_origins.py"
)
MATRAIX_WEB_MIGRATION_FILE = VERSIONS_DIRECTORY / "20260815_core_0030_matraix_web.py"
MEDIA_ARTICLE_SOURCE_PRESENCE_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260815_core_0031_media_article_source_presence.py"
)
MATRAIX_LINUX_ARTIFACT_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260815_core_0032_matraix_linux_artifact.py"
)
MATRAIX_BATCH_REGISTRY_WEB_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260816_core_0033_batch_registry_web.py"
)
MATRAIX_LINUX_EVALUATION_REGISTRY_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260816_core_0034_linux_evaluation_registry.py"
)
MATRAIX_WEB_LINUX_RETRY_MIGRATION_FILE = (
    VERSIONS_DIRECTORY / "20260816_core_0035_web_linux_retry_lineage.py"
)
TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


def _migration_sources() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(VERSIONS_DIRECTORY.glob("*core_*.py"))
    )


def test_migration_chain_has_one_distinct_core_head() -> None:
    configuration = Config(str(BACKEND_DIRECTORY / "alembic.ini"))
    scripts = ScriptDirectory.from_config(configuration)

    assert scripts.get_heads() == ["20260816_core_0035"]
    assert {revision.revision for revision in scripts.walk_revisions()} == {
        *(f"20260812_core_{position:04d}" for position in range(1, 14)),
        "20260813_core_0014",
        "20260813_core_0015",
        "20260813_core_0016",
        "20260813_core_0017",
        "20260813_core_0018",
        "20260813_core_0019",
        "20260813_core_0020",
        "20260813_core_0021",
        "20260813_core_0022",
        "20260813_core_0023",
        "20260813_core_0024",
        "20260813_core_0025",
        "20260813_core_0026",
        "20260813_core_0027",
        "20260813_core_0028",
        "20260814_core_0029",
        "20260815_core_0030",
        "20260815_core_0031",
        "20260815_core_0032",
        "20260816_core_0033",
        "20260816_core_0034",
        "20260816_core_0035",
    }


def test_enterprise_head_is_explicitly_unknown_to_the_core_lineage() -> None:
    configuration = Config(str(BACKEND_DIRECTORY / "alembic.ini"))
    scripts = ScriptDirectory.from_config(configuration)

    with pytest.raises(
        CommandError,
        match="Can't locate revision identified by '20260812_0008'",
    ):
        scripts.get_revision("20260812_0008")


def test_graph_persona_cohort_origin_migration_is_immutable_and_content_addressed() -> None:
    source = GRAPH_PERSONA_COHORT_ORIGINS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0028"' in source
    assert '"semantic_world_graph_cohort_origins"' in source
    assert "graph-persona-cohort-origin/v1" in source
    assert "graph Persona cohort origin_sha256 mismatch" in source
    assert "graph Persona cohort origins are immutable" in source
    assert "BEFORE TRUNCATE" in source


def test_matraix_web_migration_owns_bounded_append_only_browser_observations() -> None:
    source = MATRAIX_WEB_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260814_core_0029"' in source
    for table_name in (
        "matraix_web_evaluations",
        "matraix_web_trials",
        "matraix_web_pages",
        "matraix_web_quotes",
    ):
        assert f'"{table_name}"' in source
    for column_name in (
        "web_runtime_ready",
        "web_model_name",
        "web_config_sha256",
        "web_prompt_schema_version",
        "web_executor_schema_version",
        "web_executor_spec_sha256",
    ):
        assert f'"{column_name}"' in source
    assert "canonical_matraix_web_trace_sha" in source
    assert "selected quote was not present in recorded observations" in source
    assert "MatrAIx Web observations are append-only" in source
    assert "MatrAIx Web TRUNCATE is forbidden" in source


def test_media_article_source_presence_preserves_frozen_evidence_rows() -> None:
    source = MEDIA_ARTICLE_SOURCE_PRESENCE_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260815_core_0030"' in source
    assert '"source_present"' in source
    assert '"source_last_observed_at"' in source
    assert '"source_absent_at"' in source
    assert "source_absent_at >= source_last_observed_at" in source
    assert "drop_table" not in source


def test_decision_report_migration_seals_fixed_outline_and_content_hash() -> None:
    source = DECISION_REPORTS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0012"' in source
    assert '"decision_reports"' in source
    assert '"decision_report_sections"' in source
    assert "decision report content hash mismatch" in source
    assert "complete fixed outline before sealing" in source
    assert "BEFORE TRUNCATE ON decision_reports" in source
    assert "BEFORE TRUNCATE ON decision_report_sections" in source


def test_report_question_migration_owns_an_immutable_cited_answer_queue() -> None:
    source = REPORT_QUESTIONS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0013"' in source
    assert '"report_questions"' in source
    assert "report-evidence-qa/v1" in source
    assert "immutable input mismatch" in source
    assert "invalid report question state transition" in source
    assert "BEFORE TRUNCATE ON report_questions" in source

    hardening_source = REPORT_QUESTIONS_HARDENING_MIGRATION_FILE.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260813_core_0014"' in hardening_source
    assert "expected_question_sha256" in hardening_source
    assert "selected_graph.world_model_id <> selected_scenario.world_model_id" in hardening_source
    assert "BETWEEN 1 AND 800" in hardening_source

    thread_source = REPORT_QUESTION_THREADS_MIGRATION_FILE.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260813_core_0022"' in thread_source
    assert "parent_question_id" in thread_source
    assert "conversation_depth BETWEEN 1 AND 4" in thread_source
    assert "report-evidence-qa/v2" in thread_source
    assert "report question parent lineage mismatch" in thread_source


def test_matraix_survey_migration_owns_typed_append_only_results() -> None:
    source = MATRAIX_SURVEYS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0015"' in source
    assert '"matraix_survey_experiments"' in source
    assert '"matraix_survey_trials"' in source
    assert '"matraix_survey_answers"' in source
    assert '"survey_runtime_ready"' in source
    assert "preferred_variant" in source
    assert "alternative_support" in source
    assert "primary_reason" in source
    assert "queued -> running -> terminal" in source
    assert "Survey answers are append-only" in source
    assert "Survey TRUNCATE is forbidden" in source


def test_persona_interview_session_migration_seals_atomic_member_sets() -> None:
    source = PERSONA_INTERVIEW_SESSIONS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0017"' in source
    assert '"persona_interview_sessions"' in source
    assert '"persona_interview_session_members"' in source
    assert "persona-report-interview-session/v1" in source
    assert "members or digest are incomplete" in source
    assert "session members are append-only" in source
    assert "session TRUNCATE is forbidden" in source


def test_media_propagation_migration_owns_observed_country_edges() -> None:
    source = MEDIA_PROPAGATION_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0018"' in source
    assert '"media_propagation_events"' in source
    assert '"media_propagation_edges"' in source
    assert '"lag_hours"' in source
    assert '"first_article_id"' in source


def test_structured_media_propagation_preserves_follower_provenance() -> None:
    source = STRUCTURED_MEDIA_PROPAGATION_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0024"' in source
    assert '"source_follower_id"' in source
    assert '"follower_source_id"' in source
    assert '"observation_source"' in source
    assert "structured_followers" in source
    assert "uq_media_propagation_event_country" in source


def test_chat_retry_lineage_is_immutable_and_bounded() -> None:
    source = CHAT_RETRY_LINEAGE_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0025"' in source
    assert "retry_of_evaluation_id" in source
    assert "retry_of_evaluation_sha256" in source
    assert "attempt_number BETWEEN 2 AND 5" in source
    assert "matraix-chat-evaluation-retry/v1" in source
    assert "terminal parent with a failed trial" in source
    assert "cannot downgrade while Chat retry attempts exist" in source


def test_survey_retry_lineage_is_immutable_and_bounded() -> None:
    source = SURVEY_RETRY_LINEAGE_MIGRATION_FILE.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260813_core_0026"' in source
    assert "retry_of_experiment_sha256" in source
    assert "attempt_number BETWEEN 2 AND 5" in source
    assert "terminal parent with a failed trial" in source
    assert "cannot downgrade while Survey retry attempts exist" in source


def test_media_first_utterances_migration_is_evidence_bound() -> None:
    source = MEDIA_FIRST_UTTERANCES_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0027"' in source
    assert '"media_first_utterances"' in source
    assert "evidence_quote" in source
    assert "confidence='high'" in source
    assert "first_utterances" in source


def test_media_sync_migration_owns_strict_refresh_observability() -> None:
    source = MEDIA_SYNC_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0019"' in source
    assert '"media_sync_runs"' in source
    assert '"media_sync_run_tables"' in source
    assert "skipped_concurrent" in source
    assert "read_count = inserted_count + updated_count + skipped_count" in source


def test_matraix_chat_migration_owns_immutable_typed_artifacts() -> None:
    source = MATRAIX_CHAT_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0020"' in source
    assert '"matraix_chat_evaluations"' in source
    assert '"matraix_chat_trials"' in source
    assert '"matraix_chat_messages"' in source
    assert '"matraix_chat_feedback"' in source
    assert '"chat_runtime_ready"' in source
    assert "matraix_chat_sha256_nul" in source
    assert "Chat messages are append-only" in source
    assert "failed Chat trial must not retain feedback" in source
    assert "Chat trial permits only queued -> running -> terminal" in source
    assert "Chat TRUNCATE is forbidden" in source


def test_matraix_batch_registry_migration_seals_ordered_source_parents() -> None:
    source = MATRAIX_BATCH_REGISTRY_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260813_core_0021"' in source
    assert '"matraix_batch_registries"' in source
    assert '"matraix_batch_registry_items"' in source
    assert "matraix-batch-registry/v1" in source
    assert "requires 1..20 contiguous items" in source
    assert "does not match a sealed source parent" in source
    assert "hash does not match frozen inputs" in source
    assert "sealed MatrAIx batch registry items are immutable" in source
    assert "MatrAIx batch registry TRUNCATE is forbidden" in source

    web_source = MATRAIX_BATCH_REGISTRY_WEB_MIGRATION_FILE.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260815_core_0032"' in web_source
    assert "kind IN ('survey','chat','web')" in web_source
    assert "FROM matraix_web_evaluations source" in web_source
    assert "cannot downgrade while Web batch registry items exist" in web_source

    linux_source = MATRAIX_LINUX_EVALUATION_REGISTRY_MIGRATION_FILE.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260816_core_0033"' in linux_source
    assert '"matraix_linux_evaluations"' in linux_source
    assert "matraix-linux-evaluation/v1" in linux_source
    assert "kind IN ('survey','chat','web','linux')" in linux_source
    assert "FROM matraix_linux_evaluations source" in linux_source
    assert "cannot downgrade while Linux batch registry items exist" in linux_source

    retry_source = MATRAIX_WEB_LINUX_RETRY_MIGRATION_FILE.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260816_core_0034"' in retry_source
    assert "matraix-web-evaluation-retry/v1" in retry_source
    assert "matraix-linux-trial-retry/v1" in retry_source
    assert "Web retry requires a terminal parent with a failed trial" in retry_source
    assert "Linux retry lineage does not match a failed parent attempt" in retry_source
    assert "cannot downgrade while Web or Linux retry attempts exist" in retry_source


def test_core_lineage_never_reuses_enterprise_revision_ids_or_schema() -> None:
    sources = _migration_sources()

    for position in range(1, 14):
        assert f'"20260812_{position:04d}"' not in sources
    for forbidden_name in (
        "companies",
        "company_aliases",
        "world_snapshot_mentions",
        "company_id",
        "company_canonical_name",
        "company_aliases",
        "snapshot_company_name",
        "company_name",
        "snapshot_company",
    ):
        assert forbidden_name not in sources


def test_initial_migration_owns_only_media_schema_and_search_indexes() -> None:
    migration = import_module("migrations.versions.20260812_core_0001_initial_schema")
    source = MIGRATION_FILE.read_text(encoding="utf-8")

    assert "create_all" not in source
    for table_name in (
        "media_sources",
        "media_articles",
        "media_topics",
        "media_topic_articles",
        "media_topic_snapshots",
    ):
        assert f'"{table_name}"' in source
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in source
    assert "gin_trgm_ops" in source
    assert migration.TRIGRAM_INDEX_COLUMNS == {
        "ix_media_articles_title_trgm": "title",
        "ix_media_articles_content_trgm": "content",
        "ix_media_articles_summary_trgm": "summary",
    }
    for index_name in (
        "ix_media_articles_title_trgm",
        "ix_media_articles_content_trgm",
        "ix_media_articles_summary_trgm",
    ):
        assert index_name in source


def test_initial_migration_rejects_preexisting_targets_before_any_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = import_module("migrations.versions.20260812_core_0001_initial_schema")
    bind = object()
    inspector = Mock()
    inspector.has_table.side_effect = lambda table_name: table_name == "media_articles"
    get_bind = Mock(return_value=bind)
    inspect = Mock(return_value=inspector)
    execute = Mock()
    create_functions = tuple(Mock() for _table_name in migration.TARGET_MEDIA_TABLES)

    monkeypatch.setattr(migration.op, "get_bind", get_bind)
    monkeypatch.setattr(migration.sa, "inspect", inspect)
    monkeypatch.setattr(migration.op, "execute", execute)
    for table_name, create_function in zip(
        migration.TARGET_MEDIA_TABLES,
        create_functions,
        strict=True,
    ):
        monkeypatch.setattr(migration, f"_create_{table_name}", create_function)

    with pytest.raises(
        RuntimeError,
        match=(
            "requires an empty target schema; refusing to adopt pre-existing tables: media_articles"
        ),
    ):
        migration.upgrade()

    get_bind.assert_called_once_with()
    inspect.assert_called_once_with(bind)
    assert inspector.has_table.call_args_list == [
        ((table_name,), {}) for table_name in migration.TARGET_MEDIA_TABLES
    ]
    execute.assert_not_called()
    for create_function in create_functions:
        create_function.assert_not_called()


def test_world_model_migration_owns_generic_snapshot_tables() -> None:
    source = WORLD_MODELS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0001"' in source
    for table_name in (
        "world_models",
        "world_snapshots",
        "world_snapshot_evidence",
    ):
        assert f'"{table_name}"' in source
    assert 'sa.Column("title", sa.String(length=300), nullable=False)' in source
    assert "captured_text" in source
    assert "captured_text_sha256" in source
    assert "uq_world_snapshots_model_version" in source


def test_snapshot_protection_guards_both_frozen_tables() -> None:
    source = SNAPSHOT_PROTECTION_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0002"' in source
    assert "BEFORE UPDATE OR DELETE" in source
    assert "reject_world_snapshot_mutation" in source
    assert source.count('    "world_snapshot') == 2
    for table_name in ("world_snapshots", "world_snapshot_evidence"):
        assert f'"{table_name}"' in source


def test_snapshot_sealing_allows_assembly_then_rejects_mutation() -> None:
    source = SNAPSHOT_SEALING_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0003"' in source
    assert 'sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True)' in source
    assert "SET sealed_at = created_at" in source
    assert "OLD.sealed_at IS NULL" in source
    assert "NEW.sealed_at IS NOT NULL" in source
    assert "to_jsonb(NEW) - 'sealed_at'" in source
    assert "CREATE FUNCTION protect_world_snapshot_child_insert()" in source
    assert "BEFORE INSERT ON {table_name}" in source
    assert "parent_sealed_at IS NOT NULL" in source
    assert "CREATE FUNCTION reject_world_snapshot_truncate()" in source
    assert "BEFORE TRUNCATE ON {table_name}" in source
    assert "USING ERRCODE = '55000'" in source


def test_snapshot_sealing_downgrade_restores_core_0003_guards() -> None:
    source = SNAPSHOT_SEALING_MIGRATION_FILE.read_text(encoding="utf-8")
    downgrade_source = source.split("def downgrade() -> None:", maxsplit=1)[1]

    assert 'op.drop_column("world_snapshots", "sealed_at")' in downgrade_source
    assert "DROP FUNCTION protect_world_snapshot_update_delete()" in downgrade_source
    assert "DROP FUNCTION protect_world_snapshot_child_insert()" in downgrade_source
    assert "DROP FUNCTION reject_world_snapshot_truncate()" in downgrade_source
    assert "CREATE FUNCTION reject_world_snapshot_mutation()" in downgrade_source
    assert "for table_name in FROZEN_TABLES:" in downgrade_source


def test_snapshot_hardening_canonical_json_matches_application_hashing() -> None:
    migration = import_module(
        "migrations.versions.20260812_core_0005_harden_world_snapshot_sealing"
    )
    model_id = UUID("11111111-1111-4111-8111-111111111111")
    article_id = UUID("33333333-3333-4333-8333-333333333333")
    published_at = datetime(
        2026,
        8,
        12,
        16,
        30,
        1,
        123456,
        tzinfo=timezone(timedelta(hours=8)),
    )
    captured_at = datetime(2026, 8, 12, 8, 31, 2, 654321, tzinfo=UTC)
    captured_text = "政策发布\n效果明确"
    captured_text_sha256 = sha256(captured_text.encode("utf-8")).hexdigest()
    stored_evidence = migration._StoredEvidence(
        position=0,
        article_id=str(article_id),
        source_name="Example News",
        original_url="https://example.com/article",
        title="Policy update",
        captured_text=captured_text,
        published_at=published_at,
        captured_at=captured_at,
        country_code="US",
        excerpt="效果明确",
        captured_text_sha256=captured_text_sha256,
    )
    stored_snapshot = migration._StoredSnapshot(
        id="44444444-4444-4444-8444-444444444444",
        world_model_id=str(model_id),
        version=3,
        verification="human_confirmed",
        snapshot_sha256="0" * 64,
        sealed_at=captured_at,
        evidence=(stored_evidence,),
    )
    public_evidence = SnapshotEvidence(
        article_id=article_id,
        source_name="Example News",
        original_url="https://example.com/article",
        title="Policy update",
        published_at=published_at,
        captured_at=captured_at,
        country_code="US",
        excerpt="效果明确",
        captured_text_sha256=captured_text_sha256,
    )

    expected = canonical_snapshot_json(
        model_id,
        3,
        "human_confirmed",
        (public_evidence,),
    )

    assert migration._canonical_snapshot_json(stored_snapshot) == expected
    assert '"schema_version":"world-snapshot/v2"' in expected


def test_snapshot_hardening_validates_contiguity_and_both_content_hashes() -> None:
    source = SNAPSHOT_HARDENING_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0004"' in source
    assert "LOCK TABLE world_snapshots, world_snapshot_evidence" in source
    assert "IN ACCESS EXCLUSIVE MODE" in source
    assert "CREATE FUNCTION enforce_world_snapshot_draft_insert()" in source
    assert "IF NEW.sealed_at IS NOT NULL" in source
    assert "BEFORE INSERT ON world_snapshots" in source
    assert "evidence_count < 1" in source
    assert "evidence_count > 50" in source
    assert "first_evidence_position <> 0" in source
    assert "last_evidence_position <> evidence_count - 1" in source
    assert "CREATE FUNCTION canonical_world_snapshot_json" in source
    assert "sha256(convert_to(evidence.captured_text, 'UTF8'))" in source
    assert "sha256(convert_to(canonical_world_snapshot_json(NEW.id), 'UTF8'))" in source
    assert "captured_text_sha256 mismatch" in source
    assert "snapshot_sha256 mismatch" in source
    assert "invalid snapshot IDs" in source
    assert "from app." not in source


def test_snapshot_hardening_downgrade_restores_core_0004_seal_function() -> None:
    source = SNAPSHOT_HARDENING_MIGRATION_FILE.read_text(encoding="utf-8")
    downgrade_source = source.split("def downgrade() -> None:", maxsplit=1)[1]

    assert "DROP TRIGGER trg_world_snapshots_draft_insert_only" in downgrade_source
    assert "DROP FUNCTION enforce_world_snapshot_draft_insert()" in downgrade_source
    assert "DROP FUNCTION canonical_world_snapshot_json(uuid)" in downgrade_source
    assert "CREATE OR REPLACE FUNCTION protect_world_snapshot_update_delete()" in (downgrade_source)
    assert "only sealing a draft is allowed" in downgrade_source
    assert "evidence_count" not in downgrade_source


def test_scenario_migration_is_generic_and_has_complete_seal_guards() -> None:
    source = SCENARIOS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0005"' in source
    for table_name in ("scenarios", "scenario_variants", "scenario_interventions"):
        assert f'"{table_name}"' in source
        assert "BEFORE TRUNCATE ON {table_name}" in source
    assert "actor = 'scenario_actor'" in source
    assert "scenario % must be inserted as an unsealed draft" in source
    assert "selected_snapshot.sealed_at IS NULL" in source
    assert "selected_snapshot.snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256" in source
    assert "selected_evidence_count IS DISTINCT FROM NEW.snapshot_evidence_count" in source
    assert "baseline_count <> 1" in source
    assert "alternative_count < 1" in source
    assert "alternative_count > 5" in source
    assert "count(intervention.id) < 1" in source
    assert "count(intervention.id) > 20" in source
    assert "baseline interventions are forbidden" in source
    assert "CREATE FUNCTION canonical_scenario_json(target_scenario_id uuid)" in source
    assert ',"schema_version":"scenario/v2"' in source
    assert "sha256(convert_to(canonical_scenario_json(NEW.id), 'UTF8'))" in source
    assert "scenario_sha256 mismatch" in source
    assert "BEFORE INSERT OR UPDATE OR DELETE ON {table_name}" in source


def test_scenario_deduplication_enforces_canonical_identity() -> None:
    source = SCENARIO_DEDUPLICATION_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0006"' in source
    assert "LOCK TABLE scenarios IN ACCESS EXCLUSIVE MODE" in source
    assert "HAVING count(*) > 1" in source
    assert "duplicate scenario_sha256 values" in source
    assert '"uq_scenarios_sha256"' in source


def test_platform_smoke_migration_owns_generic_queue_and_transition_guards() -> None:
    source = PLATFORM_SMOKE_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_core_0007"' in source
    for table_name in (
        "simulation_runs",
        "simulation_run_posts",
        "simulation_worker_heartbeats",
    ):
        assert f'"{table_name}"' in source
    assert "input_sha256" in source
    assert "claimed_by_worker_id" in source
    assert "selected_scenario.snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256" in source
    assert "queued -> running -> terminal transitions" in source
    assert "simulation run posts are immutable" in source
    assert "BEFORE TRUNCATE ON {table_name}" in source
    assert "NEW.post_count IS DISTINCT FROM stored_post_count" in source
    assert "NEW.trace_count IS DISTINCT FROM NEW.post_count + 1" in source
    assert "CREATE FUNCTION derive_simulation_run_actor_digest(" in source
    assert "decode('00', 'hex')" in source
    assert "CREATE FUNCTION canonical_simulation_run_input_json(target_run_id uuid)" in source
    assert ',"schema_version":"oasis-platform-smoke/v2"' in source
    assert "actor does not match its deterministic scenario actor" in source
    assert "sha256(" in source
    assert "canonical_simulation_run_input_json(NEW.id)" in source
    assert "input_sha256 mismatch" in source
    assert "IF TG_OP = 'DELETE' THEN" in source
    assert "FOUND AND parent.input_sealed_at IS NOT NULL" in source


def test_population_migration_owns_content_addressed_immutable_storage() -> None:
    migration = import_module("migrations.versions.20260812_core_0009_matraix_persona_populations")
    source = POPULATIONS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert migration.down_revision == "20260812_core_0008"
    for table_name in (
        "persona_datasets",
        "personas",
        "cohorts",
        "cohort_members",
    ):
        assert f'"{table_name}"' in source
    assert 'sa.UniqueConstraint("dataset_sha256"' in source
    assert 'sa.UniqueConstraint("slug"' not in source
    assert 'op.create_index("ix_persona_datasets_slug"' in source
    assert '"schema":"matraix-persona-dataset/v1"' in source
    assert '"schema":"matraix-cohort/v1"' in source
    assert "SELECT dataset_sha256 INTO STRICT selected_dataset_sha256" in source
    assert "ORDER BY member.position" in source
    assert "FOR UPDATE;" in source
    assert "BEFORE TRUNCATE" in source
    assert "dataset_sha256 mismatch" in source
    assert "cohort_sha256 mismatch" in source


def test_semantic_migration_owns_verified_cartesian_execution_storage() -> None:
    migration = import_module("migrations.versions.20260812_core_0010_semantic_experiments")
    source = SEMANTIC_EXPERIMENTS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert migration.down_revision == "20260812_core_0009"
    for table_name in (
        "semantic_experiments",
        "semantic_experiment_variants",
        "semantic_trials",
        "semantic_trial_events",
    ):
        assert f'"{table_name}"' in source
    assert "oasis-semantic-experiment/v1" in source
    assert "oasis-semantic-trial/v1" in source
    assert "matraix-semantic-profile/v1" in source
    assert "trials are not a complete Cartesian product" in source
    assert "result counts do not match normalized events" in source
    assert "requires each cohort persona once per round" in source
    assert "event sequence must be contiguous" in source
    assert "TRUNCATE is forbidden for semantic table" in source
    assert "semantic_model_name" in source
    assert "server_default=sa.false()" in source
    assert 'alter_column("simulation_worker_heartbeats"' not in source
    assert "api_key" not in source
    assert "base_url" not in source


def test_semantic_world_graph_migration_owns_evidence_backed_queue() -> None:
    migration = import_module("migrations.versions.20260812_core_0011_semantic_world_graphs")
    source = SEMANTIC_WORLD_GRAPHS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert migration.down_revision == "20260812_core_0010"
    for table_name in (
        "semantic_world_graphs",
        "semantic_world_graph_nodes",
        "semantic_world_graph_edges",
        "semantic_world_graph_evidence",
    ):
        assert f'"{table_name}"' in source
    assert "world-graph-extraction/v1" in source
    assert "canonical_semantic_world_graph_json" in source
    assert "NEW.graph_sha256 IS DISTINCT FROM actual_graph_sha256" in source
    assert "must reference one matching sealed snapshot" in source
    assert "semantic world graph cannot seal with incomplete graph records" in source
    assert "semantic graph evidence offsets do not match frozen text" in source
    assert "semantic graph evidence article is not in the frozen snapshot" in source
    assert "terminal semantic world graphs are immutable" in source
    assert "api_key" not in source
    assert "base_url" not in source


async def _insert_single_alternative_scenario_draft(
    connection: AsyncConnection,
    scenario_id: UUID,
    scenario_sha256: str,
    title: str,
    decision_question: str,
    snapshot: ScenarioSnapshotRef,
    baseline: ScenarioVariant,
    alternative: ScenarioVariant,
    created_at: datetime,
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO scenarios (
                id, title, decision_question, world_model_id, world_snapshot_id,
                snapshot_version, snapshot_sha256, snapshot_evidence_count,
                scenario_sha256, created_at, sealed_at
            ) VALUES (
                :id, :title, :decision_question, :world_model_id, :world_snapshot_id,
                :snapshot_version, :snapshot_sha256, :snapshot_evidence_count,
                :scenario_sha256, :created_at, NULL
            )
            """
        ),
        {
            "id": scenario_id,
            "title": title,
            "decision_question": decision_question,
            "world_model_id": snapshot.world_model_id,
            "world_snapshot_id": snapshot.world_snapshot_id,
            "snapshot_version": snapshot.version,
            "snapshot_sha256": snapshot.snapshot_sha256,
            "snapshot_evidence_count": snapshot.evidence_count,
            "scenario_sha256": scenario_sha256,
            "created_at": created_at,
        },
    )
    for variant, role in ((baseline, "baseline"), (alternative, "alternative")):
        await connection.execute(
            text(
                """
                INSERT INTO scenario_variants (
                    id, scenario_id, position, role, name, hypothesis
                ) VALUES (
                    :id, :scenario_id, :position, :role, :name, :hypothesis
                )
                """
            ),
            {
                "id": variant.id,
                "scenario_id": scenario_id,
                "position": variant.position,
                "role": role,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
            },
        )
    for intervention in alternative.interventions:
        await connection.execute(
            text(
                """
                INSERT INTO scenario_interventions (
                    id, scenario_id, variant_id, position, kind, actor,
                    channel, content, offset_minutes
                ) VALUES (
                    :id, :scenario_id, :variant_id, :position, :kind, :actor,
                    :channel, :content, :offset_minutes
                )
                """
            ),
            {
                "id": intervention.id,
                "scenario_id": scenario_id,
                "variant_id": alternative.id,
                "position": intervention.position,
                "kind": intervention.kind,
                "actor": intervention.actor,
                "channel": intervention.channel,
                "content": intervention.content,
                "offset_minutes": intervention.offset_minutes,
            },
        )


async def _insert_simulation_run_draft(
    connection: AsyncConnection,
    run_id: UUID,
    compiled: CompiledPlatformSmokeInput,
    input_sha256: str,
    created_at: datetime,
) -> None:
    scenario = compiled.scenario
    await connection.execute(
        text(
            """
            INSERT INTO simulation_runs (
                id, mode, status, scenario_id, scenario_sha256, variant_id,
                variant_name, world_snapshot_id, snapshot_sha256, seed,
                actor_user_name, actor_name, actor_bio, input_sha256, created_at
            ) VALUES (
                :id, :mode, 'queued', :scenario_id, :scenario_sha256, :variant_id,
                :variant_name, :world_snapshot_id, :snapshot_sha256, :seed,
                :actor_user_name, :actor_name, :actor_bio, :input_sha256, :created_at
            )
            """
        ),
        {
            "id": run_id,
            "mode": compiled.mode,
            "scenario_id": scenario.id,
            "scenario_sha256": scenario.scenario_sha256,
            "variant_id": scenario.variant_id,
            "variant_name": scenario.variant_name,
            "world_snapshot_id": scenario.world_snapshot_id,
            "snapshot_sha256": scenario.snapshot_sha256,
            "seed": compiled.seed,
            "actor_user_name": compiled.actor_user_name,
            "actor_name": compiled.actor_name,
            "actor_bio": compiled.actor_bio,
            "input_sha256": input_sha256,
            "created_at": created_at,
        },
    )
    for post in compiled.posts:
        await connection.execute(
            text(
                """
                INSERT INTO simulation_run_posts (
                    run_id, position, content, offset_minutes
                ) VALUES (
                    :run_id, :position, :content, :offset_minutes
                )
                """
            ),
            {
                "run_id": run_id,
                "position": post.position,
                "content": post.content,
                "offset_minutes": post.offset_minutes,
            },
        )


def _test_persona_profile(persona_id: str, display_name: str) -> StoredPersonaProfile:
    return StoredPersonaProfile(
        display_name=display_name,
        dimensions={"region": "East Asia", "risk_tolerance": "Balanced"},
        persona_id=persona_id,
        provenance=StoredPersonaProvenance(
            hf_repo=None,
            origin_persona_id=None,
            origin_source_row_index=None,
            parent_pool=None,
        ),
        source="synthetic",
        version="1.0",
    )


def _canonical_test_dataset_json(
    slug: str,
    display_name: str,
    manifest_sha256: str,
    profile: StoredPersonaProfile,
    profile_sha256: str,
) -> str:
    return json.dumps(
        {
            "display_name": display_name,
            "manifest_sha256": manifest_sha256,
            "parent_pool": None,
            "persona_count": 1,
            "personas": [
                {
                    "persona_id": profile.persona_id,
                    "profile_sha256": profile_sha256,
                }
            ],
            "schema": "matraix-persona-dataset/v1",
            "schema_version": "1.0",
            "slug": slug,
            "source_repository": None,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


async def _insert_persona_dataset_draft(
    connection: AsyncConnection,
    dataset_id: UUID,
    persona_id: UUID,
    slug: str,
    display_name: str,
    manifest_sha256: str,
    profile: StoredPersonaProfile,
    profile_sha256: str,
    dataset_sha256: str,
    created_at: datetime,
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO persona_datasets (
                id, slug, display_name, schema_version, parent_pool,
                source_repository, persona_count, manifest_sha256,
                dataset_sha256, created_at, sealed_at
            ) VALUES (
                :id, :slug, :display_name, '1.0', NULL,
                NULL, 1, :manifest_sha256, :dataset_sha256, :created_at, NULL
            )
            """
        ),
        {
            "id": dataset_id,
            "slug": slug,
            "display_name": display_name,
            "manifest_sha256": manifest_sha256,
            "dataset_sha256": dataset_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO personas (
                id, dataset_id, position, persona_id, display_name,
                source, profile_json, profile_sha256
            ) VALUES (
                :id, :dataset_id, 0, :persona_id, :display_name,
                :source, CAST(:profile_json AS jsonb), :profile_sha256
            )
            """
        ),
        {
            "id": persona_id,
            "dataset_id": dataset_id,
            "persona_id": profile.persona_id,
            "display_name": profile.display_name,
            "source": profile.source,
            "profile_json": json.dumps(profile.model_dump(mode="json"), ensure_ascii=False),
            "profile_sha256": profile_sha256,
        },
    )


def _compiled_platform_input(
    scenario_id: UUID,
    scenario_sha256: str,
    alternative: ScenarioVariant,
    snapshot: ScenarioSnapshotRef,
    seed: int,
    actor_user_name: str,
    actor_name: str,
    actor_bio: str,
) -> CompiledPlatformSmokeInput:
    return CompiledPlatformSmokeInput(
        mode="reddit_manual_smoke",
        scenario=PlatformSmokeScenarioRef(
            id=scenario_id,
            scenario_sha256=scenario_sha256,
            variant_id=alternative.id,
            variant_name=alternative.name,
            world_snapshot_id=snapshot.world_snapshot_id,
            snapshot_sha256=snapshot.snapshot_sha256,
        ),
        seed=seed,
        actor_user_name=actor_user_name,
        actor_name=actor_name,
        actor_bio=actor_bio,
        posts=tuple(
            PlatformSmokePost(
                position=intervention.position,
                content=intervention.content,
                offset_minutes=intervention.offset_minutes,
            )
            for intervention in alternative.interventions
        ),
    )


async def _exercise_postgresql_content_address_guards(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                current_revision = await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                assert current_revision == "20260816_core_0035"

                created_at = datetime.now(UTC)
                world_model_id = uuid4()
                world_snapshot_id = uuid4()
                article_id = uuid4()
                captured_text = "Evidence title\nUnicode 内容 with \\\\ and a newline\nsecond line"
                captured_text_sha256 = sha256(captured_text.encode("utf-8")).hexdigest()
                evidence = SnapshotEvidence(
                    article_id=article_id,
                    source_name="Core 新闻",
                    original_url="https://example.com/core-evidence",
                    title="Evidence title",
                    published_at=created_at - timedelta(minutes=5),
                    captured_at=created_at,
                    country_code="CN",
                    excerpt="Unicode 内容",
                    captured_text_sha256=captured_text_sha256,
                )
                snapshot_sha256 = calculate_snapshot_sha256(
                    world_model_id,
                    1,
                    "human_confirmed",
                    (evidence,),
                )
                await connection.execute(
                    text(
                        "INSERT INTO world_models (id, title, created_at) "
                        "VALUES (:id, :title, :created_at)"
                    ),
                    {"id": world_model_id, "title": "Core world", "created_at": created_at},
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO world_snapshots (
                            id, world_model_id, version, verification,
                            snapshot_sha256, created_at, sealed_at
                        ) VALUES (
                            :id, :world_model_id, 1, 'human_confirmed',
                            :snapshot_sha256, :created_at, NULL
                        )
                        """
                    ),
                    {
                        "id": world_snapshot_id,
                        "world_model_id": world_model_id,
                        "snapshot_sha256": snapshot_sha256,
                        "created_at": created_at,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO world_snapshot_evidence (
                            snapshot_id, position, article_id, source_name, original_url,
                            title, captured_text, published_at, captured_at, country_code,
                            excerpt, captured_text_sha256
                        ) VALUES (
                            :snapshot_id, 0, :article_id, :source_name, :original_url,
                            :title, :captured_text, :published_at, :captured_at, :country_code,
                            :excerpt, :captured_text_sha256
                        )
                        """
                    ),
                    {
                        "snapshot_id": world_snapshot_id,
                        "article_id": article_id,
                        "source_name": evidence.source_name,
                        "original_url": str(evidence.original_url),
                        "title": evidence.title,
                        "captured_text": captured_text,
                        "published_at": evidence.published_at,
                        "captured_at": evidence.captured_at,
                        "country_code": evidence.country_code,
                        "excerpt": evidence.excerpt,
                        "captured_text_sha256": captured_text_sha256,
                    },
                )
                await connection.execute(
                    text("UPDATE world_snapshots SET sealed_at = created_at WHERE id = :id"),
                    {"id": world_snapshot_id},
                )

                snapshot = ScenarioSnapshotRef(
                    world_model_id=world_model_id,
                    world_snapshot_id=world_snapshot_id,
                    version=1,
                    snapshot_sha256=snapshot_sha256,
                    evidence_count=1,
                )
                baseline = ScenarioVariant(
                    id=uuid4(),
                    position=0,
                    name="No action",
                    hypothesis="Keep the current path.",
                    interventions=(),
                )
                alternative = ScenarioVariant(
                    id=uuid4(),
                    position=1,
                    name="Public “response”",
                    hypothesis="Explain the signal \\\\ clearly.",
                    interventions=(
                        Intervention(
                            id=uuid4(),
                            position=0,
                            kind="initial_post",
                            actor="scenario_actor",
                            channel="reddit",
                            content="发布“通用”说明。\nSecond line.",
                            offset_minutes=5,
                        ),
                        Intervention(
                            id=uuid4(),
                            position=1,
                            kind="initial_post",
                            actor="scenario_actor",
                            channel="reddit",
                            content="Follow-up with a backslash: \\\\.",
                            offset_minutes=15,
                        ),
                    ),
                )
                scenario_id = uuid4()
                scenario_title = "Generic “decision” scenario"
                decision_question = "How should this signal be addressed?"
                scenario_sha256 = calculate_scenario_sha256(
                    scenario_title,
                    decision_question,
                    snapshot,
                    baseline,
                    (alternative,),
                )
                await _insert_single_alternative_scenario_draft(
                    connection,
                    scenario_id,
                    scenario_sha256,
                    scenario_title,
                    decision_question,
                    snapshot,
                    baseline,
                    alternative,
                    created_at,
                )
                stored_scenario_json = await connection.scalar(
                    text("SELECT canonical_scenario_json(:scenario_id)"),
                    {"scenario_id": scenario_id},
                )
                assert stored_scenario_json == canonical_scenario_json(
                    scenario_title,
                    decision_question,
                    snapshot,
                    baseline,
                    (alternative,),
                )
                await connection.execute(
                    text("UPDATE scenarios SET sealed_at = created_at WHERE id = :id"),
                    {"id": scenario_id},
                )

                invalid_baseline = baseline.model_copy(update={"id": uuid4()})
                invalid_alternative = alternative.model_copy(
                    update={
                        "id": uuid4(),
                        "interventions": tuple(
                            item.model_copy(update={"id": uuid4()})
                            for item in alternative.interventions
                        ),
                    }
                )
                invalid_scenario_id = uuid4()
                await _insert_single_alternative_scenario_draft(
                    connection,
                    invalid_scenario_id,
                    "0" * 64,
                    scenario_title,
                    decision_question,
                    snapshot,
                    invalid_baseline,
                    invalid_alternative,
                    created_at,
                )
                with pytest.raises(DBAPIError, match="scenario_sha256 mismatch"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text("UPDATE scenarios SET sealed_at = created_at WHERE id = :id"),
                            {"id": invalid_scenario_id},
                        )

                compiled = _compiled_platform_input(
                    scenario_id,
                    scenario_sha256,
                    alternative,
                    snapshot,
                    42,
                    derive_scenario_actor_user_name(scenario_id, alternative.id),
                    derive_scenario_actor_name(scenario_id, alternative.id),
                    derive_scenario_actor_bio(scenario_id, alternative.id),
                )
                input_sha256 = calculate_platform_smoke_input_sha256(compiled)
                run_id = uuid4()
                await _insert_simulation_run_draft(
                    connection,
                    run_id,
                    compiled,
                    input_sha256,
                    created_at,
                )
                stored_run_json = await connection.scalar(
                    text("SELECT canonical_simulation_run_input_json(:run_id)"),
                    {"run_id": run_id},
                )
                assert stored_run_json == canonical_platform_smoke_input_json(compiled)
                await connection.execute(
                    text("UPDATE simulation_runs SET input_sealed_at = created_at WHERE id = :id"),
                    {"id": run_id},
                )

                invalid_actor = _compiled_platform_input(
                    scenario_id,
                    scenario_sha256,
                    alternative,
                    snapshot,
                    43,
                    "wrong_actor",
                    "Wrong actor",
                    "Wrong actor bio",
                )
                invalid_actor_run_id = uuid4()
                await _insert_simulation_run_draft(
                    connection,
                    invalid_actor_run_id,
                    invalid_actor,
                    calculate_platform_smoke_input_sha256(invalid_actor),
                    created_at,
                )
                with pytest.raises(DBAPIError, match="deterministic scenario actor"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE simulation_runs SET input_sealed_at = created_at "
                                "WHERE id = :id"
                            ),
                            {"id": invalid_actor_run_id},
                        )

                invalid_hash = _compiled_platform_input(
                    scenario_id,
                    scenario_sha256,
                    alternative,
                    snapshot,
                    44,
                    derive_scenario_actor_user_name(scenario_id, alternative.id),
                    derive_scenario_actor_name(scenario_id, alternative.id),
                    derive_scenario_actor_bio(scenario_id, alternative.id),
                )
                invalid_hash_run_id = uuid4()
                await _insert_simulation_run_draft(
                    connection,
                    invalid_hash_run_id,
                    invalid_hash,
                    "1" * 64,
                    created_at,
                )
                with pytest.raises(DBAPIError, match="input_sha256 mismatch"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE simulation_runs SET input_sealed_at = created_at "
                                "WHERE id = :id"
                            ),
                            {"id": invalid_hash_run_id},
                        )

                cleanup_input = _compiled_platform_input(
                    scenario_id,
                    scenario_sha256,
                    alternative,
                    snapshot,
                    45,
                    derive_scenario_actor_user_name(scenario_id, alternative.id),
                    derive_scenario_actor_name(scenario_id, alternative.id),
                    derive_scenario_actor_bio(scenario_id, alternative.id),
                )
                cleanup_run_id = uuid4()
                await _insert_simulation_run_draft(
                    connection,
                    cleanup_run_id,
                    cleanup_input,
                    calculate_platform_smoke_input_sha256(cleanup_input),
                    created_at,
                )
                deleted = await connection.execute(
                    text("DELETE FROM simulation_runs WHERE id = :id"),
                    {"id": cleanup_run_id},
                )
                assert deleted.rowcount == 1
                remaining_posts = await connection.scalar(
                    text("SELECT count(*) FROM simulation_run_posts WHERE run_id = :id"),
                    {"id": cleanup_run_id},
                )
                assert remaining_posts == 0

                profile = _test_persona_profile("migration-persona", "Migration Persona")
                profile_sha256 = calculate_persona_profile_sha256(profile)
                canonical_dataset = _canonical_test_dataset_json(
                    "migration-test",
                    "Migration test",
                    "1" * 64,
                    profile,
                    profile_sha256,
                )
                dataset_sha256 = sha256(canonical_dataset.encode("utf-8")).hexdigest()
                dataset_id = uuid4()
                persona_record_id = uuid4()
                await _insert_persona_dataset_draft(
                    connection,
                    dataset_id,
                    persona_record_id,
                    "migration-test",
                    "Migration test",
                    "1" * 64,
                    profile,
                    profile_sha256,
                    dataset_sha256,
                    created_at,
                )
                stored_canonical_dataset = await connection.scalar(
                    text("SELECT canonical_matraix_persona_dataset_json(:dataset_id)"),
                    {"dataset_id": dataset_id},
                )
                assert stored_canonical_dataset == canonical_dataset
                await connection.execute(
                    text(
                        "UPDATE persona_datasets SET sealed_at = created_at WHERE id = :dataset_id"
                    ),
                    {"dataset_id": dataset_id},
                )
                with pytest.raises(DBAPIError, match="sealed.*INSERT on personas is forbidden"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                INSERT INTO personas (
                                    id, dataset_id, position, persona_id, display_name,
                                    source, profile_json, profile_sha256
                                ) SELECT
                                    :id, dataset_id, 1, 'late-persona', 'Late Persona',
                                    source, profile_json, profile_sha256
                                FROM personas WHERE id = :existing_id
                                """
                            ),
                            {"id": uuid4(), "existing_id": persona_record_id},
                        )

                invalid_profile = profile.model_dump(mode="json")
                invalid_profile["display_name"] = 7
                invalid_dataset_id = uuid4()
                invalid_persona_record_id = uuid4()
                await connection.execute(
                    text(
                        """
                        INSERT INTO persona_datasets (
                            id, slug, display_name, schema_version, persona_count,
                            manifest_sha256, dataset_sha256, created_at, sealed_at
                        ) VALUES (
                            :id, 'invalid-profile', 'Invalid profile', '1.0', 1,
                            :manifest_sha256, :dataset_sha256, :created_at, NULL
                        )
                        """
                    ),
                    {
                        "id": invalid_dataset_id,
                        "manifest_sha256": "2" * 64,
                        "dataset_sha256": "2" * 64,
                        "created_at": created_at,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO personas (
                            id, dataset_id, position, persona_id, display_name,
                            source, profile_json, profile_sha256
                        ) VALUES (
                            :id, :dataset_id, 0, :persona_id, '7',
                            :source, CAST(:profile_json AS jsonb), :profile_sha256
                        )
                        """
                    ),
                    {
                        "id": invalid_persona_record_id,
                        "dataset_id": invalid_dataset_id,
                        "persona_id": profile.persona_id,
                        "source": profile.source,
                        "profile_json": json.dumps(invalid_profile),
                        "profile_sha256": "2" * 64,
                    },
                )
                with pytest.raises(DBAPIError, match="profile is invalid"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE persona_datasets SET sealed_at = created_at "
                                "WHERE id = :dataset_id"
                            ),
                            {"dataset_id": invalid_dataset_id},
                        )

                invalid_provenance_profile = profile.model_dump(mode="json")
                invalid_provenance_profile["provenance"] = {
                    "hf_repo": 7,
                    "origin_persona_id": None,
                    "origin_source_row_index": -1,
                    "parent_pool": None,
                }
                invalid_provenance_dataset_id = uuid4()
                await connection.execute(
                    text(
                        """
                        INSERT INTO persona_datasets (
                            id, slug, display_name, schema_version, persona_count,
                            manifest_sha256, dataset_sha256, created_at, sealed_at
                        ) VALUES (
                            :id, 'invalid-provenance', 'Invalid provenance', '1.0', 1,
                            :manifest_sha256, :dataset_sha256, :created_at, NULL
                        )
                        """
                    ),
                    {
                        "id": invalid_provenance_dataset_id,
                        "manifest_sha256": "3" * 64,
                        "dataset_sha256": "3" * 64,
                        "created_at": created_at,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO personas (
                            id, dataset_id, position, persona_id, display_name,
                            source, profile_json, profile_sha256
                        ) VALUES (
                            :id, :dataset_id, 0, :persona_id, :display_name,
                            :source, CAST(:profile_json AS jsonb), :profile_sha256
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "dataset_id": invalid_provenance_dataset_id,
                        "persona_id": profile.persona_id,
                        "display_name": profile.display_name,
                        "source": profile.source,
                        "profile_json": json.dumps(invalid_provenance_profile),
                        "profile_sha256": "3" * 64,
                    },
                )
                with pytest.raises(DBAPIError, match="profile is invalid"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE persona_datasets SET sealed_at = created_at "
                                "WHERE id = :dataset_id"
                            ),
                            {"dataset_id": invalid_provenance_dataset_id},
                        )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def _exercise_population_seal_child_lock(database_url: str) -> None:
    """Prove a child write waits for an in-flight dataset seal row lock."""
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    dataset_id = uuid4()
    persona_record_id = uuid4()
    late_persona_record_id = uuid4()
    slug = f"seal-lock-{dataset_id.hex[:12]}"
    display_name = "Seal lock test"
    manifest_sha256 = sha256(dataset_id.bytes).hexdigest()
    profile = _test_persona_profile(f"persona-{dataset_id.hex[:12]}", "Lock Persona")
    profile_sha256 = calculate_persona_profile_sha256(profile)
    canonical_dataset = _canonical_test_dataset_json(
        slug,
        display_name,
        manifest_sha256,
        profile,
        profile_sha256,
    )
    dataset_sha256 = sha256(canonical_dataset.encode("utf-8")).hexdigest()
    try:
        async with engine.begin() as setup_connection:
            await _insert_persona_dataset_draft(
                setup_connection,
                dataset_id,
                persona_record_id,
                slug,
                display_name,
                manifest_sha256,
                profile,
                profile_sha256,
                dataset_sha256,
                datetime.now(UTC),
            )

        async with (
            engine.connect() as seal_connection,
            engine.connect() as child_connection,
        ):
            seal_transaction = await seal_connection.begin()
            child_transaction = await child_connection.begin()
            child_insert: asyncio.Task[object] | None = None
            try:
                await seal_connection.execute(
                    text(
                        "UPDATE persona_datasets SET sealed_at = created_at WHERE id = :dataset_id"
                    ),
                    {"dataset_id": dataset_id},
                )
                child_insert = asyncio.create_task(
                    child_connection.execute(
                        text(
                            """
                            INSERT INTO personas (
                                id, dataset_id, position, persona_id, display_name,
                                source, profile_json, profile_sha256
                            ) SELECT
                                :id, dataset_id, 1, 'late-persona', 'Late Persona',
                                source, profile_json, profile_sha256
                            FROM personas WHERE id = :existing_id
                            """
                        ),
                        {"id": late_persona_record_id, "existing_id": persona_record_id},
                    )
                )
                await asyncio.sleep(0.2)
                assert not child_insert.done(), (
                    "persona child insert bypassed the in-flight dataset seal row lock"
                )
                await seal_transaction.rollback()
                await asyncio.wait_for(child_insert, timeout=2)
            finally:
                if seal_transaction.is_active:
                    await seal_transaction.rollback()
                if child_insert is not None and not child_insert.done():
                    child_insert.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await child_insert
                if child_transaction.is_active:
                    await child_transaction.rollback()

        async with engine.begin() as cleanup_connection:
            await cleanup_connection.execute(
                text("DELETE FROM persona_datasets WHERE id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
    finally:
        await engine.dispose()


async def _insert_semantic_fixture(
    connection: AsyncConnection,
    created_at: datetime,
) -> tuple[UUID, UUID, UUID, UUID, UUID, str]:
    """Build sealed source resources and one valid sealed semantic experiment."""
    world_model_id = uuid4()
    snapshot_id = uuid4()
    evidence_text = "Semantic migration evidence"
    evidence = SnapshotEvidence(
        article_id=uuid4(),
        source_name="Semantic test source",
        original_url="https://example.com/semantic-test",
        title="Semantic test evidence",
        published_at=created_at,
        captured_at=created_at,
        country_code="CN",
        excerpt="Semantic test evidence",
        captured_text_sha256=sha256(evidence_text.encode()).hexdigest(),
    )
    snapshot_sha = calculate_snapshot_sha256(
        world_model_id,
        1,
        "human_confirmed",
        (evidence,),
    )
    await connection.execute(
        text(
            "INSERT INTO world_models (id,title,created_at) "
            "VALUES (:id,'Semantic migration model',:created_at)"
        ),
        {"id": world_model_id, "created_at": created_at},
    )
    await connection.execute(
        text(
            """
            INSERT INTO world_snapshots (
                id,world_model_id,version,verification,snapshot_sha256,created_at,sealed_at
            ) VALUES (:id,:model_id,1,'human_confirmed',:digest,:created_at,NULL)
            """
        ),
        {
            "id": snapshot_id,
            "model_id": world_model_id,
            "digest": snapshot_sha,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO world_snapshot_evidence (
                snapshot_id,position,article_id,source_name,original_url,title,captured_text,
                published_at,captured_at,country_code,excerpt,captured_text_sha256
            ) VALUES (
                :snapshot,0,:article,:source,:url,:title,:captured_text,
                :published_at,:captured_at,:country,:excerpt,:text_sha
            )
            """
        ),
        {
            "snapshot": snapshot_id,
            "article": evidence.article_id,
            "source": evidence.source_name,
            "url": str(evidence.original_url),
            "title": evidence.title,
            "captured_text": evidence_text,
            "published_at": evidence.published_at,
            "captured_at": evidence.captured_at,
            "country": evidence.country_code,
            "excerpt": evidence.excerpt,
            "text_sha": evidence.captured_text_sha256,
        },
    )
    await connection.execute(
        text("UPDATE world_snapshots SET sealed_at=created_at WHERE id=:id"),
        {"id": snapshot_id},
    )
    scenario_id = uuid4()
    snapshot = ScenarioSnapshotRef(
        world_model_id=world_model_id,
        world_snapshot_id=snapshot_id,
        version=1,
        snapshot_sha256=snapshot_sha,
        evidence_count=1,
    )
    baseline = ScenarioVariant(
        id=uuid4(),
        position=0,
        name="No action",
        hypothesis="Observe baseline",
        interventions=(),
    )
    alternative = ScenarioVariant(
        id=uuid4(),
        position=1,
        name="Clarify",
        hypothesis="Observe clarification",
        interventions=(
            Intervention(
                id=uuid4(),
                position=0,
                kind="initial_post",
                actor="scenario_actor",
                channel="reddit",
                content="Verified facts",
                offset_minutes=0,
            ),
        ),
    )
    scenario_sha = calculate_scenario_sha256(
        "Semantic scenario",
        "What is observed?",
        snapshot,
        baseline,
        (alternative,),
    )
    await _insert_single_alternative_scenario_draft(
        connection,
        scenario_id,
        scenario_sha,
        "Semantic scenario",
        "What is observed?",
        snapshot,
        baseline,
        alternative,
        created_at,
    )
    await connection.execute(
        text("UPDATE scenarios SET sealed_at=created_at WHERE id=:id"), {"id": scenario_id}
    )
    dataset_id = uuid4()
    persona_id = uuid4()
    cohort_id = uuid4()
    profile = _test_persona_profile("semantic-persona", "Semantic Persona")
    profile_sha = calculate_persona_profile_sha256(profile)
    slug = f"semantic-{dataset_id.hex[:12]}"
    manifest_sha = "3" * 64
    dataset_sha = sha256(
        _canonical_test_dataset_json(
            slug,
            "Semantic dataset",
            manifest_sha,
            profile,
            profile_sha,
        ).encode()
    ).hexdigest()
    await _insert_persona_dataset_draft(
        connection,
        dataset_id,
        persona_id,
        slug,
        "Semantic dataset",
        manifest_sha,
        profile,
        profile_sha,
        dataset_sha,
        created_at,
    )
    await connection.execute(
        text("UPDATE persona_datasets SET sealed_at=created_at WHERE id=:id"),
        {"id": dataset_id},
    )
    cohort_sha = calculate_cohort_sha256(
        "Semantic cohort",
        dataset_sha,
        ((profile.persona_id, profile_sha),),
    )
    await connection.execute(
        text(
            """
            INSERT INTO cohorts (
                id,dataset_id,title,persona_count,cohort_sha256,created_at,sealed_at
            ) VALUES (:id,:dataset_id,'Semantic cohort',1,:digest,:created_at,NULL)
            """
        ),
        {
            "id": cohort_id,
            "dataset_id": dataset_id,
            "digest": cohort_sha,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            "INSERT INTO cohort_members (cohort_id,dataset_id,persona_id,position) "
            "VALUES (:cohort,:dataset,:persona,0)"
        ),
        {"cohort": cohort_id, "dataset": dataset_id, "persona": persona_id},
    )
    await connection.execute(
        text("UPDATE cohorts SET sealed_at=created_at WHERE id=:id"), {"id": cohort_id}
    )
    variants = (
        FrozenSemanticVariant(
            position=0,
            role="baseline",
            id=baseline.id,
            scenario_position=0,
            name="No action",
            hypothesis="Observe baseline",
            intervention_count=0,
        ),
        FrozenSemanticVariant(
            position=1,
            role="alternative",
            id=alternative.id,
            scenario_position=1,
            name="Clarify",
            hypothesis="Observe clarification",
            intervention_count=1,
        ),
    )
    experiment_id = uuid4()
    experiment_sha = calculate_semantic_experiment_sha256(
        str(scenario_id),
        scenario_sha,
        str(cohort_id),
        cohort_sha,
        variants,
        (7,),
        1,
        30,
        "semantic-model",
        "6" * 64,
    )
    await connection.execute(
        text(
            """
            INSERT INTO semantic_experiments (
                id,scenario_id,scenario_sha256,scenario_title,decision_question,
                cohort_id,cohort_sha256,cohort_title,dataset_sha256,persona_count,
                rounds,minutes_per_round,model_name,semantic_config_sha256,
                prompt_schema_version,experiment_sha256,created_at,input_sealed_at
            ) VALUES (
                :id,:scenario_id,:scenario_sha,'Semantic scenario','What is observed?',
                :cohort_id,:cohort_sha,'Semantic cohort',:dataset_sha,1,
                1,30,'semantic-model',:config_sha,:prompt,:experiment_sha,:created_at,NULL
            )
            """
        ),
        {
            "id": experiment_id,
            "scenario_id": scenario_id,
            "scenario_sha": scenario_sha,
            "cohort_id": cohort_id,
            "cohort_sha": cohort_sha,
            "dataset_sha": dataset_sha,
            "config_sha": "6" * 64,
            "prompt": PROMPT_SCHEMA_VERSION,
            "experiment_sha": experiment_sha,
            "created_at": created_at,
        },
    )
    for variant in variants:
        await connection.execute(
            text(
                """
                INSERT INTO semantic_experiment_variants (
                    experiment_id,position,role,scenario_variant_id,scenario_position,
                    name,hypothesis,intervention_count
                ) VALUES (
                    :experiment,:position,:role,:variant,:scenario_position,
                    :name,:hypothesis,:intervention_count
                )
                """
            ),
            {
                "experiment": experiment_id,
                "position": variant.position,
                "role": variant.role,
                "variant": variant.id,
                "scenario_position": variant.scenario_position,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
                "intervention_count": variant.intervention_count,
            },
        )
    trial_ids: list[UUID] = []
    for variant in variants:
        trial_id = uuid4()
        trial_ids.append(trial_id)
        await connection.execute(
            text(
                """
                INSERT INTO semantic_trials (
                    id,experiment_id,variant_position,variant_role,scenario_variant_id,
                    scenario_position,variant_name,variant_hypothesis,seed,trial_sha256,
                    status,current_round,created_at
                ) VALUES (
                    :id,:experiment,:position,:role,:variant,:scenario_position,
                    :name,:hypothesis,7,:trial_sha,'queued',0,:created_at
                )
                """
            ),
            {
                "id": trial_id,
                "experiment": experiment_id,
                "position": variant.position,
                "role": variant.role,
                "variant": variant.id,
                "scenario_position": variant.scenario_position,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
                "trial_sha": calculate_semantic_trial_sha256(experiment_sha, variant, 7),
                "created_at": created_at,
            },
        )
    await connection.execute(
        text("UPDATE semantic_experiments SET input_sealed_at=:at WHERE id=:id"),
        {"id": experiment_id, "at": created_at},
    )
    return (
        experiment_id,
        trial_ids[0],
        trial_ids[1],
        persona_id,
        alternative.id,
        experiment_sha,
    )


async def _clone_semantic_draft(
    connection: AsyncConnection,
    source_experiment_id: UUID,
    model_name: str,
    config_sha256: str,
    wrong_experiment_hash: bool,
    wrong_trial_hash: bool,
) -> UUID:
    """Clone source selections into an unsealed hash-negative-test batch."""
    source = (
        (
            await connection.execute(
                text("SELECT * FROM semantic_experiments WHERE id=:id"),
                {"id": source_experiment_id},
            )
        )
        .mappings()
        .one()
    )
    variant_rows = tuple(
        (
            await connection.execute(
                text(
                    "SELECT * FROM semantic_experiment_variants "
                    "WHERE experiment_id=:id ORDER BY position"
                ),
                {"id": source_experiment_id},
            )
        )
        .mappings()
        .all()
    )
    variants = tuple(
        FrozenSemanticVariant(
            position=row["position"],
            role=row["role"],
            id=row["scenario_variant_id"],
            scenario_position=row["scenario_position"],
            name=row["name"],
            hypothesis=row["hypothesis"],
            intervention_count=row["intervention_count"],
        )
        for row in variant_rows
    )
    correct_hash = calculate_semantic_experiment_sha256(
        str(source["scenario_id"]),
        source["scenario_sha256"],
        str(source["cohort_id"]),
        source["cohort_sha256"],
        variants,
        (7,),
        source["rounds"],
        source["minutes_per_round"],
        model_name,
        config_sha256,
    )
    stored_hash = "e" * 64 if wrong_experiment_hash else correct_hash
    experiment_id = uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO semantic_experiments (
                id,scenario_id,scenario_sha256,scenario_title,decision_question,
                cohort_id,cohort_sha256,cohort_title,dataset_sha256,persona_count,
                rounds,minutes_per_round,model_name,semantic_config_sha256,
                prompt_schema_version,experiment_sha256,created_at,input_sealed_at
            ) SELECT
                :id,scenario_id,scenario_sha256,scenario_title,decision_question,
                cohort_id,cohort_sha256,cohort_title,dataset_sha256,persona_count,
                rounds,minutes_per_round,:model,:config,prompt_schema_version,
                :experiment_hash,created_at,NULL
            FROM semantic_experiments WHERE id=:source
            """
        ),
        {
            "id": experiment_id,
            "source": source_experiment_id,
            "model": model_name,
            "config": config_sha256,
            "experiment_hash": stored_hash,
        },
    )
    for variant in variants:
        await connection.execute(
            text(
                """
                INSERT INTO semantic_experiment_variants (
                    experiment_id,position,role,scenario_variant_id,scenario_position,
                    name,hypothesis,intervention_count
                ) VALUES (
                    :experiment,:position,:role,:variant,:scenario_position,
                    :name,:hypothesis,:intervention_count
                )
                """
            ),
            {
                "experiment": experiment_id,
                "position": variant.position,
                "role": variant.role,
                "variant": variant.id,
                "scenario_position": variant.scenario_position,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
                "intervention_count": variant.intervention_count,
            },
        )
        trial_hash = calculate_semantic_trial_sha256(stored_hash, variant, 7)
        if wrong_trial_hash and variant.position == 1:
            trial_hash = "f" * 64
        await connection.execute(
            text(
                """
                INSERT INTO semantic_trials (
                    id,experiment_id,variant_position,variant_role,scenario_variant_id,
                    scenario_position,variant_name,variant_hypothesis,seed,trial_sha256,
                    status,current_round,created_at
                ) SELECT
                    :id,:experiment,:position,:role,:variant,:scenario_position,
                    :name,:hypothesis,7,:trial_hash,'queued',0,created_at
                FROM semantic_experiments WHERE id=:experiment
                """
            ),
            {
                "id": uuid4(),
                "experiment": experiment_id,
                "position": variant.position,
                "role": variant.role,
                "variant": variant.id,
                "scenario_position": variant.scenario_position,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
                "trial_hash": trial_hash,
            },
        )
    return experiment_id


async def _exercise_semantic_guards(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                created_at = datetime.now(UTC)
                await connection.execute(
                    text(
                        "DELETE FROM simulation_worker_heartbeats "
                        "WHERE semantic_runtime_ready IS TRUE"
                    )
                )
                (
                    experiment_id,
                    baseline_trial,
                    alternative_trial,
                    persona_id,
                    _,
                    _,
                ) = await _insert_semantic_fixture(connection, created_at)
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as repository_session:
                    queued_detail = await get_semantic_experiment(
                        repository_session,
                        experiment_id,
                    )
                    assert queued_detail.status == "queued"
                    assert queued_detail.seeds == (7,)
                    assert tuple(variant.role for variant in queued_detail.variants) == (
                        "baseline",
                        "alternative",
                    )
                invalid_experiment = await _clone_semantic_draft(
                    connection,
                    experiment_id,
                    "semantic-model-invalid-experiment",
                    "9" * 64,
                    True,
                    False,
                )
                with pytest.raises(DBAPIError, match="experiment_sha256 mismatch"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE semantic_experiments SET input_sealed_at=created_at "
                                "WHERE id=:id"
                            ),
                            {"id": invalid_experiment},
                        )
                await connection.execute(
                    text("DELETE FROM semantic_experiments WHERE id=:id"),
                    {"id": invalid_experiment},
                )
                invalid_trial = await _clone_semantic_draft(
                    connection,
                    experiment_id,
                    "semantic-model-invalid-trial",
                    "a" * 64,
                    False,
                    True,
                )
                with pytest.raises(DBAPIError, match="trial_sha256 mismatch"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE semantic_experiments SET input_sealed_at=created_at "
                                "WHERE id=:id"
                            ),
                            {"id": invalid_trial},
                        )
                await connection.execute(
                    text("DELETE FROM semantic_experiments WHERE id=:id"),
                    {"id": invalid_trial},
                )
                await connection.execute(
                    text(
                        "UPDATE semantic_trials SET status='running',"
                        "claimed_by_worker_id='pg-test',started_at=:at "
                        "WHERE id IN (:baseline,:alternative)"
                    ),
                    {
                        "baseline": baseline_trial,
                        "alternative": alternative_trial,
                        "at": created_at,
                    },
                )
                with pytest.raises(DBAPIError, match="permits only queued -> running"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text("UPDATE semantic_trials SET current_round=2 WHERE id=:id"),
                            {"id": alternative_trial},
                        )
                await connection.execute(
                    text(
                        """
                        INSERT INTO semantic_trial_events (
                            trial_id,sequence,round,phase,actor_kind,persona_id,
                            agent_position,action_type,observed_at_raw,recorded_at
                        ) VALUES (
                            :trial,1,1,'audience','persona',:persona,1,
                            'do_nothing','round-1',:at
                        )
                        """
                    ),
                    {"trial": baseline_trial, "persona": persona_id, "at": created_at},
                )
                with pytest.raises(DBAPIError, match="event sequence must be contiguous"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                INSERT INTO semantic_trial_events (
                                    trial_id,sequence,round,phase,actor_kind,persona_id,
                                    agent_position,action_type,observed_at_raw,recorded_at
                                ) VALUES (
                                    :trial,3,1,'audience','persona',:persona,1,
                                    'do_nothing','round-1-duplicate',:at
                                )
                                """
                            ),
                            {"trial": baseline_trial, "persona": persona_id, "at": created_at},
                        )
                with pytest.raises(DBAPIError, match="persona/agent does not match frozen cohort"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                INSERT INTO semantic_trial_events (
                                    trial_id,sequence,round,phase,actor_kind,persona_id,
                                    agent_position,action_type,observed_at_raw,recorded_at
                                ) VALUES (
                                    :trial,2,1,'audience','persona',:persona,2,
                                    'do_nothing','wrong-agent',:at
                                )
                                """
                            ),
                            {"trial": baseline_trial, "persona": persona_id, "at": created_at},
                        )
                with pytest.raises(DBAPIError, match="round 1 audience events are incomplete"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE semantic_trials SET current_round=1 "
                                "WHERE id=:id RETURNING id"
                            ),
                            {"id": alternative_trial},
                        )
                with pytest.raises(
                    DBAPIError, match="interventions through round 1 are incomplete"
                ):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                INSERT INTO semantic_trial_events (
                                    trial_id,sequence,round,phase,actor_kind,persona_id,
                                    agent_position,action_type,content,post_id,
                                    observed_at_raw,recorded_at
                                ) VALUES (
                                    :trial,1,1,'intervention','scenario',NULL,0,
                                    'create_post','Wrong intervention','wrong-post','wrong',:at
                                )
                                """
                            ),
                            {"trial": alternative_trial, "at": created_at},
                        )
                        await connection.execute(
                            text(
                                """
                                INSERT INTO semantic_trial_events (
                                    trial_id,sequence,round,phase,actor_kind,persona_id,
                                    agent_position,action_type,observed_at_raw,recorded_at
                                ) VALUES (
                                    :trial,2,1,'audience','persona',:persona,1,
                                    'do_nothing','audience',:at
                                )
                                """
                            ),
                            {
                                "trial": alternative_trial,
                                "persona": persona_id,
                                "at": created_at,
                            },
                        )
                        await connection.execute(
                            text("UPDATE semantic_trials SET current_round=1 WHERE id=:id"),
                            {"id": alternative_trial},
                        )
                await connection.execute(
                    text("UPDATE semantic_trials SET current_round=1 WHERE id=:id"),
                    {"id": baseline_trial},
                )
                with pytest.raises(
                    DBAPIError, match="result counts do not match normalized events"
                ):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                UPDATE semantic_trials SET
                                    status='succeeded',completed_at=:at,engine_version='0.2.5',
                                    camel_version='0.2.78',model_name='semantic-model',
                                    semantic_config_sha256=:config,prompt_schema_version=:prompt,
                                    artifact_sha256=:artifact,artifact_size_bytes=1,user_count=2,
                                    initial_post_count=0,generated_post_count=0,comment_count=0,
                                    reaction_count=0,do_nothing_count=0,observed_action_count=0,
                                    rounds_completed=1,limitations=ARRAY['synthetic observation']
                                WHERE id=:id
                                """
                            ),
                            {
                                "id": baseline_trial,
                                "at": created_at,
                                "config": "6" * 64,
                                "prompt": PROMPT_SCHEMA_VERSION,
                                "artifact": "7" * 64,
                            },
                        )
                await connection.execute(
                    text(
                        """
                        UPDATE semantic_trials SET
                            status='succeeded',completed_at=:at,engine_version='0.2.5',
                            camel_version='0.2.78',model_name='semantic-model',
                            semantic_config_sha256=:config,prompt_schema_version=:prompt,
                            artifact_sha256=:artifact,artifact_size_bytes=1,user_count=2,
                            initial_post_count=0,generated_post_count=0,comment_count=0,
                            reaction_count=0,do_nothing_count=1,observed_action_count=1,
                            rounds_completed=1,limitations=ARRAY['synthetic observation']
                        WHERE id=:id
                        """
                    ),
                    {
                        "id": baseline_trial,
                        "at": created_at,
                        "config": "6" * 64,
                        "prompt": PROMPT_SCHEMA_VERSION,
                        "artifact": "7" * 64,
                    },
                )
                with pytest.raises(DBAPIError, match="append-only"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text("DELETE FROM semantic_trial_events WHERE trial_id=:id"),
                            {"id": baseline_trial},
                        )
                with pytest.raises(DBAPIError, match="TRUNCATE is forbidden"):
                    async with connection.begin_nested():
                        await connection.execute(text("TRUNCATE semantic_trial_events"))
                with pytest.raises(DBAPIError, match="trial DELETE is forbidden"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text("DELETE FROM semantic_trials WHERE id=:id"),
                            {"id": alternative_trial},
                        )
                draft_id = uuid4()
                await connection.execute(
                    text(
                        """
                        INSERT INTO semantic_experiments (
                            id,scenario_id,scenario_sha256,scenario_title,decision_question,
                            cohort_id,cohort_sha256,cohort_title,dataset_sha256,persona_count,
                            rounds,minutes_per_round,model_name,semantic_config_sha256,
                            prompt_schema_version,experiment_sha256,created_at,input_sealed_at
                        ) SELECT
                            :id,scenario_id,scenario_sha256,scenario_title,decision_question,
                            cohort_id,cohort_sha256,cohort_title,dataset_sha256,persona_count,
                            rounds,minutes_per_round,model_name,semantic_config_sha256,
                            prompt_schema_version,:hash,created_at,NULL
                        FROM semantic_experiments WHERE id=:source
                        """
                    ),
                    {"id": draft_id, "source": experiment_id, "hash": "8" * 64},
                )
                deleted = await connection.execute(
                    text("DELETE FROM semantic_experiments WHERE id=:id"), {"id": draft_id}
                )
                assert deleted.rowcount == 1
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def _exercise_semantic_api_postgresql(database_url: str) -> None:
    """Exercise every semantic HTTP read/create path against one real PG transaction."""
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture_statement)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                created_at = datetime.now(UTC)
                await connection.execute(
                    text(
                        "DELETE FROM simulation_worker_heartbeats "
                        "WHERE semantic_runtime_ready IS TRUE"
                    )
                )
                (
                    experiment_id,
                    baseline_trial,
                    _,
                    _,
                    alternative_id,
                    _,
                ) = await _insert_semantic_fixture(connection, created_at)
                source = (
                    (
                        await connection.execute(
                            text(
                                "SELECT scenario_id,cohort_id FROM semantic_experiments "
                                "WHERE id=:id"
                            ),
                            {"id": experiment_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO simulation_worker_heartbeats (
                            worker_id,engine,engine_version,camel_version,mode,
                            platform_runtime_ready,semantic_runtime_ready,semantic_model_name,
                            semantic_config_sha256,semantic_prompt_schema_version,
                            started_at,last_seen_at
                        ) VALUES (
                            :worker,'camel-oasis','0.2.5','0.2.78','reddit_manual_smoke',
                            true,true,'semantic-model',:config,:prompt,:at,:at
                        )
                        ON CONFLICT (worker_id) DO UPDATE SET last_seen_at=EXCLUDED.last_seen_at
                        """
                    ),
                    {
                        "worker": f"semantic-api-test-{experiment_id.hex[:12]}",
                        "config": "6" * 64,
                        "prompt": PROMPT_SCHEMA_VERSION,
                        "at": created_at,
                    },
                )
                application = create_app(load_runtime_settings({}))

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_semantic_experiment_session] = (
                    session_override
                )
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://semantic-test",
                ) as client:
                    create_response = await client.post(
                        "/api/v2/semantic-experiments",
                        json={
                            "scenario_id": str(source["scenario_id"]),
                            "cohort_id": str(source["cohort_id"]),
                            "alternative_ids": [str(alternative_id)],
                            "seeds": [7],
                            "rounds": 1,
                            "minutes_per_round": 30,
                        },
                    )
                    assert create_response.status_code == 202
                    assert create_response.json()["id"] == str(experiment_id)

                    statements.clear()
                    list_response = await client.get("/api/v2/semantic-experiments")
                    assert list_response.status_code == 200
                    assert any(
                        item["id"] == str(experiment_id) for item in list_response.json()["items"]
                    )
                    assert not any("semantic_trial_events" in statement for statement in statements)

                    detail_response = await client.get(
                        f"/api/v2/semantic-experiments/{experiment_id}"
                    )
                    assert detail_response.status_code == 200
                    assert detail_response.json()["status"] == "queued"

                    events_response = await client.get(
                        f"/api/v2/semantic-trials/{baseline_trial}/events",
                        params={"after_sequence": 0, "limit": 100},
                    )
                    assert events_response.status_code == 200
                    assert events_response.json()["items"] == []

                    comparison_response = await client.get(
                        f"/api/v2/semantic-experiments/{experiment_id}/comparison"
                    )
                    assert comparison_response.status_code == 200
                    comparison = comparison_response.json()
                    assert comparison["state"] == "pending"
                    assert [metric["metric"] for metric in comparison["metrics"]] == [
                        "observed_action_count",
                        "authored_content_count",
                        "reaction_count",
                        "do_nothing_count",
                    ]

                    readiness_response = await client.get(
                        "/api/v2/simulations/oasis/semantic-readiness"
                    )
                    assert readiness_response.status_code == 200
                    readiness = readiness_response.json()
                    assert readiness["semantic_runtime_ready"] is True
                    assert readiness["model_name"] == "semantic-model"
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for migration guard behavior tests",
)
def test_postgresql_content_addresses_are_enforced_when_resources_are_sealed() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_postgresql_content_address_guards(TEST_POSTGRES_DATABASE_URL))


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for population concurrency tests",
)
def test_population_child_write_waits_for_concurrent_dataset_seal() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_population_seal_child_lock(TEST_POSTGRES_DATABASE_URL))


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for semantic guard behavior tests",
)
def test_semantic_postgresql_guards_verify_events_progress_and_results() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_semantic_guards(TEST_POSTGRES_DATABASE_URL))


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for semantic API integration tests",
)
def test_semantic_http_endpoints_execute_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_semantic_api_postgresql(TEST_POSTGRES_DATABASE_URL))


def test_compose_uses_a_stable_isolated_core_namespace() -> None:
    source = (REPOSITORY_DIRECTORY / "compose.yaml").read_text(encoding="utf-8")

    assert source.startswith("name: sendowl\n")
    for volume_name in (
        "sendowl-postgres-data",
        "sendowl-redis-data",
        "sendowl-oasis-artifacts",
        "sendowl-web-artifacts",
        "sendowl-linux-artifacts",
    ):
        assert f"name: {volume_name}" in source
    assert source.count("image: sendowl-") == 10
    assert "ai-decision-center-core" not in source


def test_postgresql_test_profile_is_isolated_from_application_data() -> None:
    compose_source = (REPOSITORY_DIRECTORY / "compose.yaml").read_text(encoding="utf-8")
    test_services = compose_source.split("  postgres-test:", maxsplit=1)[1].split(
        "\n  redis:", maxsplit=1
    )[0]
    dockerfile = (REPOSITORY_DIRECTORY / "backend" / "Dockerfile").read_text(encoding="utf-8")
    package = (REPOSITORY_DIRECTORY / "package.json").read_text(encoding="utf-8")
    runner = (REPOSITORY_DIRECTORY / "scripts" / "test-backend-postgresql.sh").read_text(
        encoding="utf-8"
    )

    assert test_services.count("profiles:\n      - test") == 2
    assert "- /var/lib/postgresql/data" in test_services
    assert "ports:" not in test_services
    assert "postgres_data" not in test_services
    assert "target: test" in test_services
    assert "@postgres-test:5432/sendowl_test" in test_services
    assert "tests/run_postgresql.sh" in test_services
    assert "FROM base AS test" in dockerfile
    assert "FROM base AS production" in dockerfile
    assert 'CMD ["/bin/sh", "tests/run_postgresql.sh"]' in dockerfile
    assert '"test:backend:postgres": "sh scripts/test-backend-postgresql.sh"' in package
    assert "stop postgres-test" in runner


def test_sendowl_local_defaults_do_not_reuse_legacy_demo_ports_or_database() -> None:
    environment = (REPOSITORY_DIRECTORY / ".env.example").read_text(encoding="utf-8")
    package = (REPOSITORY_DIRECTORY / "package.json").read_text(encoding="utf-8")
    vite = (REPOSITORY_DIRECTORY / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

    assert "FRONTEND_PORT=3200" in environment
    assert "BACKEND_PORT=8210" in environment
    assert "POSTGRES_DB=sendowl" in environment
    assert "POSTGRES_USER=sendowl" in environment
    assert "SENDOWL_ENV_FILE" in package
    assert "--port 8310 --reload" in package
    assert "port: 3300" in vite
    assert 'target: "http://127.0.0.1:8310"' in vite
    assert "ADC_ENV_FILE" not in package
