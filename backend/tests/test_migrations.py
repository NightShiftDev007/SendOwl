"""Migration-chain and production schema ownership checks."""

from datetime import UTC, datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.companies.contracts import CompanyEvidenceContext
from app.world_models.contracts import SnapshotCompany, SnapshotEvidence
from app.world_models.hashing import canonical_snapshot_json

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0001_initial_v2_schema.py"
)
WORLD_MODELS_MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0002_world_models.py"
)
SNAPSHOT_PROTECTION_MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0003_protect_world_snapshots.py"
)
SNAPSHOT_SEALING_MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0004_seal_world_snapshots.py"
)
SNAPSHOT_HARDENING_MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0005_harden_world_snapshot_sealing.py"
)
SCENARIOS_MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0006_immutable_scenarios.py"
)
SCENARIO_DEDUPLICATION_MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0007_deduplicate_scenario_specs.py"
)
PLATFORM_SMOKE_MIGRATION_FILE = (
    BACKEND_DIRECTORY / "migrations" / "versions" / "20260812_0008_oasis_platform_smoke_runs.py"
)


def test_migration_chain_has_one_head() -> None:
    configuration = Config(str(BACKEND_DIRECTORY / "alembic.ini"))
    scripts = ScriptDirectory.from_config(configuration)

    assert scripts.get_heads() == ["20260812_0008"]


def test_initial_migration_explicitly_owns_current_schema_and_search_indexes() -> None:
    source = MIGRATION_FILE.read_text(encoding="utf-8")

    assert "create_all" not in source
    for table_name in (
        "media_sources",
        "media_articles",
        "media_topics",
        "media_topic_articles",
        "media_topic_snapshots",
        "companies",
        "company_aliases",
    ):
        assert f'"{table_name}"' in source
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in source
    assert source.count("gin_trgm_ops") >= 2
    for index_name in (
        "ix_media_articles_title_trgm",
        "ix_media_articles_content_trgm",
        "ix_media_articles_summary_trgm",
    ):
        assert index_name in source


def test_world_model_migration_is_additive_and_owns_frozen_snapshot_tables() -> None:
    source = WORLD_MODELS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_0001"' in source
    for table_name in (
        "world_models",
        "world_snapshots",
        "world_snapshot_evidence",
        "world_snapshot_mentions",
    ):
        assert f'"{table_name}"' in source
    assert "captured_text" in source
    assert "uq_world_snapshots_model_version" in source


def test_snapshot_protection_migration_guards_every_frozen_table() -> None:
    source = SNAPSHOT_PROTECTION_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_0002"' in source
    assert "BEFORE UPDATE OR DELETE" in source
    assert "reject_world_snapshot_mutation" in source
    for table_name in (
        "world_snapshots",
        "world_snapshot_evidence",
        "world_snapshot_mentions",
    ):
        assert f'"{table_name}"' in source


def test_snapshot_sealing_migration_backfills_existing_rows_and_allows_only_sealing() -> None:
    source = SNAPSHOT_SEALING_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_0003"' in source
    assert 'sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True)' in source
    assert "SET sealed_at = created_at" in source
    assert "OLD.sealed_at IS NULL" in source
    assert "NEW.sealed_at IS NOT NULL" in source
    assert "to_jsonb(NEW) - 'sealed_at'" in source
    assert "to_jsonb(OLD) - 'sealed_at'" in source
    assert "USING ERRCODE = '55000'" in source


def test_snapshot_sealing_migration_rejects_children_after_seal_and_all_truncation() -> None:
    source = SNAPSHOT_SEALING_MIGRATION_FILE.read_text(encoding="utf-8")

    assert "CREATE FUNCTION protect_world_snapshot_child_insert()" in source
    assert "BEFORE INSERT ON {table_name}" in source
    assert "parent_sealed_at IS NOT NULL" in source
    assert "FOR UPDATE" in source
    assert "CREATE FUNCTION reject_world_snapshot_truncate()" in source
    assert "BEFORE TRUNCATE ON {table_name}" in source
    assert "FOR EACH STATEMENT" in source
    for table_name in (
        "world_snapshots",
        "world_snapshot_evidence",
        "world_snapshot_mentions",
    ):
        assert f'"{table_name}"' in source


def test_snapshot_sealing_downgrade_restores_revision_0003_guards() -> None:
    source = SNAPSHOT_SEALING_MIGRATION_FILE.read_text(encoding="utf-8")
    downgrade_source = source.split("def downgrade() -> None:", maxsplit=1)[1]

    assert 'op.drop_column("world_snapshots", "sealed_at")' in downgrade_source
    assert "DROP FUNCTION protect_world_snapshot_update_delete()" in downgrade_source
    assert "DROP FUNCTION protect_world_snapshot_child_insert()" in downgrade_source
    assert "DROP FUNCTION reject_world_snapshot_truncate()" in downgrade_source
    assert "CREATE FUNCTION reject_world_snapshot_mutation()" in downgrade_source
    assert "for table_name in FROZEN_TABLES:" in downgrade_source
    assert "BEFORE UPDATE OR DELETE ON {table_name}" in downgrade_source
    for table_name in (
        "world_snapshots",
        "world_snapshot_evidence",
        "world_snapshot_mentions",
    ):
        assert f'"{table_name}"' in source


def test_snapshot_hardening_migration_preflights_exact_frozen_content() -> None:
    source = SNAPSHOT_HARDENING_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_0004"' in source
    assert "LOCK TABLE world_snapshots, world_snapshot_evidence" in source
    assert "IN ACCESS EXCLUSIVE MODE" in source
    assert "captured_text_sha256 mismatch" in source
    assert "snapshot_sha256 mismatch" in source
    assert "surface form mismatch" in source
    assert "invalid snapshot IDs" in source
    assert "from app." not in source


def test_snapshot_hardening_canonical_json_matches_application_hashing() -> None:
    migration = import_module("migrations.versions.20260812_0005_harden_world_snapshot_sealing")
    model_id = UUID("11111111-1111-4111-8111-111111111111")
    company_id = UUID("22222222-2222-4222-8222-222222222222")
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
    captured_text = "Acme opens\nAcme grows"
    captured_text_sha256 = "6fd061c950267f85aa4c589f721a3c9ba82b38684cd5770bd11b4e8aff350a6c"
    stored_mentions = (
        migration._StoredMention(0, "Acme", "Acme", 0, 4, captured_text),
        migration._StoredMention(1, "ACME", "Acme", 11, 15, captured_text),
    )
    stored_evidence = migration._StoredEvidence(
        position=0,
        article_id=str(article_id),
        source_name="Example News",
        original_url="https://example.com/acme",
        title="Acme opens",
        captured_text=captured_text,
        published_at=published_at,
        captured_at=captured_at,
        country_code="US",
        excerpt="Acme grows",
        captured_text_sha256=captured_text_sha256,
        mentions=stored_mentions,
    )
    stored_snapshot = migration._StoredSnapshot(
        id="44444444-4444-4444-8444-444444444444",
        world_model_id=str(model_id),
        version=3,
        verification="human_confirmed",
        snapshot_sha256="0" * 64,
        sealed_at=captured_at,
        company_id=str(company_id),
        company_canonical_name="Acme",
        company_aliases=("Acme Inc.",),
        evidence=(stored_evidence,),
    )
    public_evidence = SnapshotEvidence(
        article_id=article_id,
        source_name="Example News",
        original_url="https://example.com/acme",
        title="Acme opens",
        published_at=published_at,
        captured_at=captured_at,
        country_code="US",
        excerpt="Acme grows",
        captured_text_sha256=captured_text_sha256,
        matched_aliases=("Acme",),
        evidence_contexts=(
            CompanyEvidenceContext(
                alias="Acme",
                start_offset=0,
                end_offset=4,
                context=captured_text,
            ),
            CompanyEvidenceContext(
                alias="ACME",
                start_offset=11,
                end_offset=15,
                context=captured_text,
            ),
        ),
    )

    expected = canonical_snapshot_json(
        model_id,
        3,
        "human_confirmed",
        SnapshotCompany(
            id=company_id,
            canonical_name="Acme",
            aliases=("Acme Inc.",),
        ),
        (public_evidence,),
    )

    assert migration._canonical_snapshot_json(stored_snapshot) == expected


def test_snapshot_hardening_requires_draft_insert_and_complete_contiguous_children() -> None:
    source = SNAPSHOT_HARDENING_MIGRATION_FILE.read_text(encoding="utf-8")

    assert "CREATE FUNCTION enforce_world_snapshot_draft_insert()" in source
    assert "IF NEW.sealed_at IS NOT NULL" in source
    assert "BEFORE INSERT ON world_snapshots" in source
    assert "evidence_count < 1" in source
    assert "evidence_count > 50" in source
    assert "first_evidence_position <> 0" in source
    assert "last_evidence_position <> evidence_count - 1" in source
    assert "count(mention.position) < 1" in source
    assert "min(mention.position) <> 0" in source
    assert "max(mention.position) <> count(mention.position) - 1" in source


def test_snapshot_hardening_downgrade_restores_revision_0004_seal_function() -> None:
    source = SNAPSHOT_HARDENING_MIGRATION_FILE.read_text(encoding="utf-8")
    downgrade_source = source.split("def downgrade() -> None:", maxsplit=1)[1]

    assert "DROP TRIGGER trg_world_snapshots_draft_insert_only" in downgrade_source
    assert "DROP FUNCTION enforce_world_snapshot_draft_insert()" in downgrade_source
    assert "CREATE OR REPLACE FUNCTION protect_world_snapshot_update_delete()" in (downgrade_source)
    assert "only sealing a draft is allowed" in downgrade_source
    assert "evidence_count" not in downgrade_source


def test_scenario_migration_owns_normalized_tables_and_complete_seal_guard() -> None:
    source = SCENARIOS_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_0005"' in source
    for table_name in ("scenarios", "scenario_variants", "scenario_interventions"):
        assert f'"{table_name}"' in source
        assert "BEFORE TRUNCATE ON {table_name}" in source
    assert "scenario % must be inserted as an unsealed draft" in source
    assert "selected_snapshot.sealed_at IS NULL" in source
    assert "baseline_count <> 1" in source
    assert "alternative_count < 1" in source
    assert "alternative_count > 5" in source
    assert "count(intervention.id) < 1" in source
    assert "count(intervention.id) > 20" in source
    assert "baseline interventions are forbidden" in source
    assert "BEFORE INSERT OR UPDATE OR DELETE ON {table_name}" in source
    assert "USING ERRCODE = '55000'" in source


def test_scenario_migration_downgrade_removes_guards_before_tables() -> None:
    source = SCENARIOS_MIGRATION_FILE.read_text(encoding="utf-8")
    downgrade_source = source.split("def downgrade() -> None:", maxsplit=1)[1]

    assert downgrade_source.index("DROP TRIGGER") < downgrade_source.index(
        'op.drop_table("scenario_interventions")'
    )
    assert "DROP FUNCTION enforce_scenario_draft_insert()" in downgrade_source
    assert "DROP FUNCTION protect_scenario_update_delete()" in downgrade_source
    assert "DROP FUNCTION protect_scenario_child_mutation()" in downgrade_source
    assert "DROP FUNCTION reject_scenario_truncate()" in downgrade_source


def test_scenario_deduplication_preflights_and_enforces_canonical_identity() -> None:
    source = SCENARIO_DEDUPLICATION_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_0006"' in source
    assert "LOCK TABLE scenarios IN ACCESS EXCLUSIVE MODE" in source
    assert "HAVING count(*) > 1" in source
    assert "duplicate scenario_sha256 values" in source
    assert '"uq_scenarios_sha256"' in source


def test_platform_smoke_migration_owns_queue_heartbeat_and_transition_guards() -> None:
    source = PLATFORM_SMOKE_MIGRATION_FILE.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260812_0007"' in source
    for table_name in (
        "simulation_runs",
        "simulation_run_posts",
        "simulation_worker_heartbeats",
    ):
        assert f'"{table_name}"' in source
    assert "input_sha256" in source
    assert "claimed_by_worker_id" in source
    assert "queued -> running -> terminal transitions" in source
    assert "simulation run posts are immutable" in source
    assert "BEFORE TRUNCATE ON {table_name}" in source
    assert "NEW.post_count IS DISTINCT FROM stored_post_count" in source
    assert "NEW.trace_count IS DISTINCT FROM NEW.post_count + 1" in source
