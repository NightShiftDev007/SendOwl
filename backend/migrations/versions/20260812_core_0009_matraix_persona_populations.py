"""Create immutable MatrAIx persona datasets and cohorts.

Revision ID: 20260812_core_0009
Revises: 20260812_core_0008
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0009"
down_revision: str | None = "20260812_core_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_tables() -> None:
    op.create_table(
        "persona_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("parent_pool", sa.String(length=500), nullable=True),
        sa.Column("source_repository", sa.String(length=500), nullable=True),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "slug ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_persona_datasets_slug",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 200 AND display_name !~ E'[\\r\\n]'",
            name="ck_persona_datasets_display_name",
        ),
        sa.CheckConstraint(
            "schema_version ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_persona_datasets_schema_version",
        ),
        sa.CheckConstraint(
            "parent_pool IS NULL OR "
            "(length(btrim(parent_pool)) BETWEEN 1 AND 500 AND parent_pool !~ E'[\\r\\n]')",
            name="ck_persona_datasets_parent_pool",
        ),
        sa.CheckConstraint(
            "source_repository IS NULL OR "
            "(length(btrim(source_repository)) BETWEEN 1 AND 500 "
            "AND source_repository !~ E'[\\r\\n]')",
            name="ck_persona_datasets_source_repository",
        ),
        sa.CheckConstraint(
            "persona_count BETWEEN 1 AND 1000000",
            name="ck_persona_datasets_persona_count",
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_datasets_manifest_sha256",
        ),
        sa.CheckConstraint(
            "dataset_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_datasets_dataset_sha256",
        ),
        sa.CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_persona_datasets_sealed_time",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_sha256", name="uq_persona_datasets_dataset_sha256"),
    )
    op.create_index("ix_persona_datasets_slug", "persona_datasets", ["slug"])
    op.create_index("ix_persona_datasets_created_at", "persona_datasets", ["created_at"])

    op.create_table(
        "personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 999999",
            name="ck_personas_position",
        ),
        sa.CheckConstraint(
            "persona_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_personas_persona_id",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 200 AND display_name !~ E'[\\r\\n]'",
            name="ck_personas_display_name",
        ),
        sa.CheckConstraint(
            "source ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_personas_source",
        ),
        sa.CheckConstraint(
            "profile_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_personas_profile_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["persona_datasets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "persona_id", name="uq_personas_dataset_persona_id"),
        sa.UniqueConstraint("dataset_id", "position", name="uq_personas_dataset_position"),
        sa.UniqueConstraint("dataset_id", "id", name="uq_personas_dataset_id"),
    )
    op.create_index("ix_personas_dataset_source", "personas", ["dataset_id", "source"])

    op.create_table(
        "cohorts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 200 AND title !~ E'[\\r\\n]'",
            name="ck_cohorts_title",
        ),
        sa.CheckConstraint(
            "persona_count BETWEEN 1 AND 100",
            name="ck_cohorts_persona_count",
        ),
        sa.CheckConstraint(
            "cohort_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_cohorts_cohort_sha256",
        ),
        sa.CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_cohorts_sealed_time",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["persona_datasets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cohort_sha256", name="uq_cohorts_cohort_sha256"),
        sa.UniqueConstraint("id", "dataset_id", name="uq_cohorts_id_dataset"),
    )
    op.create_index("ix_cohorts_dataset_created_at", "cohorts", ["dataset_id", "created_at"])

    op.create_table(
        "cohort_members",
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 99",
            name="ck_cohort_members_position",
        ),
        sa.ForeignKeyConstraint(
            ["cohort_id", "dataset_id"],
            ["cohorts.id", "cohorts.dataset_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "persona_id"],
            ["personas.dataset_id", "personas.id"],
        ),
        sa.PrimaryKeyConstraint("cohort_id", "position"),
        sa.UniqueConstraint("cohort_id", "persona_id", name="uq_cohort_members_persona"),
    )
    op.create_index(
        "ix_cohort_members_dataset_persona",
        "cohort_members",
        ["dataset_id", "persona_id"],
    )


def _create_canonical_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION canonical_matraix_persona_profile_json(target_persona_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected_persona personas%ROWTYPE;
            dimensions_json text;
            provenance jsonb;
        BEGIN
            SELECT * INTO selected_persona
            FROM personas
            WHERE id = target_persona_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cannot canonicalize missing persona %', target_persona_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT string_agg(
                to_json(dimension.key)::text || ':' || to_json(dimension.value)::text,
                ',' ORDER BY dimension.key
            )
            INTO dimensions_json
            FROM jsonb_each_text(selected_persona.profile_json -> 'dimensions') AS dimension;

            provenance := selected_persona.profile_json -> 'provenance';
            RETURN '{"dimensions":{' || coalesce(dimensions_json, '') || '}' ||
                ',"display_name":' || to_json(selected_persona.display_name)::text ||
                ',"persona_id":' || to_json(selected_persona.persona_id)::text ||
                ',"provenance":{"hf_repo":' ||
                    coalesce(to_json(provenance ->> 'hf_repo')::text, 'null') ||
                ',"origin_persona_id":' ||
                    coalesce(to_json(provenance ->> 'origin_persona_id')::text, 'null') ||
                ',"origin_source_row_index":' ||
                    coalesce(provenance ->> 'origin_source_row_index', 'null') ||
                ',"parent_pool":' ||
                    coalesce(to_json(provenance ->> 'parent_pool')::text, 'null') || '}' ||
                ',"source":' || to_json(selected_persona.source)::text ||
                ',"version":' || to_json(selected_persona.profile_json ->> 'version')::text ||
                '}';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION canonical_matraix_persona_dataset_json(target_dataset_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected_dataset persona_datasets%ROWTYPE;
            personas_json text;
        BEGIN
            SELECT * INTO selected_dataset
            FROM persona_datasets
            WHERE id = target_dataset_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cannot canonicalize missing persona dataset %', target_dataset_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT string_agg(
                '{"persona_id":' || to_json(persona.persona_id)::text ||
                ',"profile_sha256":' || to_json(persona.profile_sha256)::text || '}',
                ',' ORDER BY persona.position
            )
            INTO personas_json
            FROM personas AS persona
            WHERE persona.dataset_id = target_dataset_id;

            RETURN '{"display_name":' || to_json(selected_dataset.display_name)::text ||
                ',"manifest_sha256":' || to_json(selected_dataset.manifest_sha256)::text ||
                ',"parent_pool":' ||
                    coalesce(to_json(selected_dataset.parent_pool)::text, 'null') ||
                ',"persona_count":' || selected_dataset.persona_count::text ||
                ',"personas":[' || coalesce(personas_json, '') || ']' ||
                ',"schema":"matraix-persona-dataset/v1"' ||
                ',"schema_version":' || to_json(selected_dataset.schema_version)::text ||
                ',"slug":' || to_json(selected_dataset.slug)::text ||
                ',"source_repository":' ||
                    coalesce(to_json(selected_dataset.source_repository)::text, 'null') ||
                '}';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION canonical_matraix_cohort_json(target_cohort_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected_cohort cohorts%ROWTYPE;
            selected_dataset_sha256 text;
            members_json text;
        BEGIN
            SELECT * INTO selected_cohort
            FROM cohorts
            WHERE id = target_cohort_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cannot canonicalize missing cohort %', target_cohort_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT dataset_sha256 INTO STRICT selected_dataset_sha256
            FROM persona_datasets
            WHERE id = selected_cohort.dataset_id;

            SELECT string_agg(
                '{"persona_id":' || to_json(persona.persona_id)::text ||
                ',"profile_sha256":' || to_json(persona.profile_sha256)::text || '}',
                ',' ORDER BY member.position
            )
            INTO members_json
            FROM cohort_members AS member
            JOIN personas AS persona
              ON persona.dataset_id = member.dataset_id
             AND persona.id = member.persona_id
            WHERE member.cohort_id = target_cohort_id;

            RETURN '{"dataset_sha256":' || to_json(selected_dataset_sha256)::text ||
                ',"members":[' || coalesce(members_json, '') || ']' ||
                ',"persona_count":' || selected_cohort.persona_count::text ||
                ',"schema":"matraix-cohort/v1"' ||
                ',"title":' || to_json(selected_cohort.title)::text ||
                '}';
        END;
        $$
        """
    )


def _create_dataset_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_persona_dataset_draft_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'persona dataset % must be inserted as an unsealed draft', NEW.id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_persona_dataset_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            actual_count bigint;
            first_position integer;
            last_position integer;
            invalid_persona_id uuid;
            actual_dataset_sha256 text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.sealed_at IS NULL THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION
                    'persona dataset % is sealed; DELETE is forbidden', OLD.id
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.sealed_at IS NULL
               AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW) - 'sealed_at') = (to_jsonb(OLD) - 'sealed_at')
            THEN
                SELECT count(*), min(position), max(position)
                INTO actual_count, first_position, last_position
                FROM personas
                WHERE dataset_id = NEW.id;
                IF actual_count <> NEW.persona_count
                   OR first_position <> 0
                   OR last_position <> actual_count - 1
                THEN
                    RAISE EXCEPTION
                        'persona dataset % cannot be sealed; expected % contiguous personas '
                        'starting at zero but found %',
                        NEW.id, NEW.persona_count, actual_count
                        USING ERRCODE = '55000';
                END IF;

                SELECT persona.id
                INTO invalid_persona_id
                FROM personas AS persona
                WHERE persona.dataset_id = NEW.id
                  AND (
                    jsonb_typeof(persona.profile_json) IS DISTINCT FROM 'object'
                    OR NOT persona.profile_json ?& ARRAY[
                        'display_name', 'dimensions', 'persona_id',
                        'provenance', 'source', 'version'
                    ]
                    OR persona.profile_json - ARRAY[
                        'display_name', 'dimensions', 'persona_id',
                        'provenance', 'source', 'version'
                    ] <> '{}'::jsonb
                    OR jsonb_typeof(persona.profile_json -> 'display_name') <> 'string'
                    OR jsonb_typeof(persona.profile_json -> 'persona_id') <> 'string'
                    OR jsonb_typeof(persona.profile_json -> 'source') <> 'string'
                    OR jsonb_typeof(persona.profile_json -> 'version') <> 'string'
                    OR persona.profile_json ->> 'persona_id'
                        IS DISTINCT FROM persona.persona_id
                    OR persona.profile_json ->> 'display_name'
                        IS DISTINCT FROM persona.display_name
                    OR persona.profile_json ->> 'source'
                        IS DISTINCT FROM persona.source
                    OR coalesce(persona.profile_json ->> 'version', '')
                        !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'
                    OR jsonb_typeof(persona.profile_json -> 'dimensions')
                        IS DISTINCT FROM 'object'
                    OR jsonb_typeof(persona.profile_json -> 'provenance')
                        IS DISTINCT FROM 'object'
                    OR NOT (persona.profile_json -> 'provenance') ?& ARRAY[
                        'hf_repo', 'origin_persona_id',
                        'origin_source_row_index', 'parent_pool'
                    ]
                    OR (persona.profile_json -> 'provenance') - ARRAY[
                        'hf_repo', 'origin_persona_id',
                        'origin_source_row_index', 'parent_pool'
                    ] <> '{}'::jsonb
                    OR jsonb_typeof(
                        persona.profile_json -> 'provenance' -> 'hf_repo'
                    ) NOT IN ('string', 'null')
                    OR (
                        jsonb_typeof(
                            persona.profile_json -> 'provenance' -> 'hf_repo'
                        ) = 'string'
                        AND (
                            length(btrim(
                                persona.profile_json -> 'provenance' ->> 'hf_repo'
                            )) NOT BETWEEN 1 AND 500
                            OR persona.profile_json -> 'provenance' ->> 'hf_repo'
                                ~ E'[\\r\\n]'
                        )
                    )
                    OR jsonb_typeof(
                        persona.profile_json -> 'provenance' -> 'origin_persona_id'
                    ) NOT IN ('string', 'null')
                    OR (
                        jsonb_typeof(
                            persona.profile_json -> 'provenance' -> 'origin_persona_id'
                        ) = 'string'
                        AND (
                            length(btrim(
                                persona.profile_json -> 'provenance' ->> 'origin_persona_id'
                            )) NOT BETWEEN 1 AND 128
                            OR persona.profile_json -> 'provenance' ->> 'origin_persona_id'
                                ~ E'[\\r\\n]'
                        )
                    )
                    OR jsonb_typeof(
                        persona.profile_json -> 'provenance' -> 'parent_pool'
                    ) NOT IN ('string', 'null')
                    OR (
                        jsonb_typeof(
                            persona.profile_json -> 'provenance' -> 'parent_pool'
                        ) = 'string'
                        AND (
                            length(btrim(
                                persona.profile_json -> 'provenance' ->> 'parent_pool'
                            )) NOT BETWEEN 1 AND 500
                            OR persona.profile_json -> 'provenance' ->> 'parent_pool'
                                ~ E'[\\r\\n]'
                        )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_each(persona.profile_json -> 'dimensions') AS dimension
                        WHERE dimension.key !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
                           OR jsonb_typeof(dimension.value) <> 'string'
                           OR length(btrim(dimension.value #>> '{}')) NOT BETWEEN 1 AND 500
                           OR (dimension.value #>> '{}') ~ E'[\\r\\n]'
                    )
                    OR jsonb_typeof(
                        persona.profile_json -> 'provenance' -> 'origin_source_row_index'
                    ) NOT IN ('number', 'null')
                    OR (
                        jsonb_typeof(
                            persona.profile_json -> 'provenance' -> 'origin_source_row_index'
                        ) = 'number'
                        AND persona.profile_json -> 'provenance'
                            ->> 'origin_source_row_index' !~ '^[0-9]+$'
                    )
                    OR encode(
                        sha256(convert_to(
                            canonical_matraix_persona_profile_json(persona.id), 'UTF8'
                        )),
                        'hex'
                    ) IS DISTINCT FROM persona.profile_sha256
                  )
                ORDER BY persona.position
                LIMIT 1;
                IF FOUND THEN
                    RAISE EXCEPTION
                        'persona dataset % cannot be sealed; persona % profile is invalid '
                        'or profile_sha256 mismatches',
                        NEW.id, invalid_persona_id
                        USING ERRCODE = '55000';
                END IF;

                actual_dataset_sha256 := encode(
                    sha256(convert_to(canonical_matraix_persona_dataset_json(NEW.id), 'UTF8')),
                    'hex'
                );
                IF actual_dataset_sha256 IS DISTINCT FROM NEW.dataset_sha256 THEN
                    RAISE EXCEPTION
                        'persona dataset % cannot be sealed; dataset_sha256 mismatch', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'persona dataset % is sealed; UPDATE is forbidden', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            RAISE EXCEPTION
                'persona dataset % draft may only transition to sealed', OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_persona_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_sealed_at timestamp with time zone;
        BEGIN
            SELECT sealed_at INTO parent_sealed_at
            FROM persona_datasets
            WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.dataset_id ELSE NEW.dataset_id END
            FOR UPDATE;
            IF FOUND AND parent_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'persona dataset % is sealed; % on personas is forbidden',
                    CASE WHEN TG_OP = 'DELETE' THEN OLD.dataset_id ELSE NEW.dataset_id END,
                    TG_OP
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.dataset_id IS DISTINCT FROM NEW.dataset_id THEN
                SELECT sealed_at INTO parent_sealed_at
                FROM persona_datasets
                WHERE id = OLD.dataset_id
                FOR UPDATE;
                IF FOUND AND parent_sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'persona dataset % is sealed; moving a persona is forbidden', OLD.dataset_id
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_persona_datasets_draft_insert_only
        BEFORE INSERT ON persona_datasets
        FOR EACH ROW EXECUTE FUNCTION enforce_persona_dataset_draft_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_persona_datasets_protect_update_delete
        BEFORE UPDATE OR DELETE ON persona_datasets
        FOR EACH ROW EXECUTE FUNCTION protect_persona_dataset_update_delete()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_personas_protect_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON personas
        FOR EACH ROW EXECUTE FUNCTION protect_persona_mutation()
        """
    )


def _create_cohort_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_cohort_draft_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_sealed_at timestamp with time zone;
        BEGIN
            IF NEW.sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'cohort % must be inserted as an unsealed draft', NEW.id
                    USING ERRCODE = '55000';
            END IF;
            SELECT sealed_at INTO parent_sealed_at
            FROM persona_datasets
            WHERE id = NEW.dataset_id
            FOR UPDATE;
            IF NOT FOUND OR parent_sealed_at IS NULL THEN
                RAISE EXCEPTION
                    'cohort % requires sealed persona dataset %', NEW.id, NEW.dataset_id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_cohort_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            actual_count bigint;
            first_position integer;
            last_position integer;
            actual_cohort_sha256 text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.sealed_at IS NULL THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION
                    'cohort % is sealed; DELETE is forbidden', OLD.id
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.sealed_at IS NULL
               AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW) - 'sealed_at') = (to_jsonb(OLD) - 'sealed_at')
            THEN
                SELECT count(*), min(position), max(position)
                INTO actual_count, first_position, last_position
                FROM cohort_members
                WHERE cohort_id = NEW.id;
                IF actual_count <> NEW.persona_count
                   OR first_position <> 0
                   OR last_position <> actual_count - 1
                THEN
                    RAISE EXCEPTION
                        'cohort % cannot be sealed; expected % contiguous members '
                        'starting at zero but found %',
                        NEW.id, NEW.persona_count, actual_count
                        USING ERRCODE = '55000';
                END IF;

                actual_cohort_sha256 := encode(
                    sha256(convert_to(canonical_matraix_cohort_json(NEW.id), 'UTF8')),
                    'hex'
                );
                IF actual_cohort_sha256 IS DISTINCT FROM NEW.cohort_sha256 THEN
                    RAISE EXCEPTION
                        'cohort % cannot be sealed; cohort_sha256 mismatch', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'cohort % is sealed; UPDATE is forbidden', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            RAISE EXCEPTION
                'cohort % draft may only transition to sealed', OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_cohort_member_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_sealed_at timestamp with time zone;
        BEGIN
            SELECT sealed_at INTO parent_sealed_at
            FROM cohorts
            WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.cohort_id ELSE NEW.cohort_id END
            FOR UPDATE;
            IF FOUND AND parent_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'cohort % is sealed; % on cohort members is forbidden',
                    CASE WHEN TG_OP = 'DELETE' THEN OLD.cohort_id ELSE NEW.cohort_id END,
                    TG_OP
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.cohort_id IS DISTINCT FROM NEW.cohort_id THEN
                SELECT sealed_at INTO parent_sealed_at
                FROM cohorts
                WHERE id = OLD.cohort_id
                FOR UPDATE;
                IF FOUND AND parent_sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'cohort % is sealed; moving a member is forbidden', OLD.cohort_id
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_cohorts_draft_insert_only
        BEFORE INSERT ON cohorts
        FOR EACH ROW EXECUTE FUNCTION enforce_cohort_draft_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_cohorts_protect_update_delete
        BEFORE UPDATE OR DELETE ON cohorts
        FOR EACH ROW EXECUTE FUNCTION protect_cohort_update_delete()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_cohort_members_protect_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON cohort_members
        FOR EACH ROW EXECUTE FUNCTION protect_cohort_member_mutation()
        """
    )


def _create_truncate_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_population_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            sealed_rows_exist boolean;
        BEGIN
            IF TG_TABLE_NAME = 'persona_datasets' THEN
                SELECT EXISTS(SELECT 1 FROM persona_datasets WHERE sealed_at IS NOT NULL)
                INTO sealed_rows_exist;
            ELSIF TG_TABLE_NAME = 'personas' THEN
                SELECT EXISTS(
                    SELECT 1 FROM personas AS persona
                    JOIN persona_datasets AS dataset ON dataset.id = persona.dataset_id
                    WHERE dataset.sealed_at IS NOT NULL
                ) INTO sealed_rows_exist;
            ELSIF TG_TABLE_NAME = 'cohorts' THEN
                SELECT EXISTS(SELECT 1 FROM cohorts WHERE sealed_at IS NOT NULL)
                INTO sealed_rows_exist;
            ELSE
                SELECT EXISTS(
                    SELECT 1 FROM cohort_members AS member
                    JOIN cohorts AS cohort ON cohort.id = member.cohort_id
                    WHERE cohort.sealed_at IS NOT NULL
                ) INTO sealed_rows_exist;
            END IF;
            IF sealed_rows_exist THEN
                RAISE EXCEPTION
                    '% contains sealed population resources; TRUNCATE is forbidden',
                    TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    for table_name in ("persona_datasets", "personas", "cohorts", "cohort_members"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_protect_truncate
            BEFORE TRUNCATE ON {table_name}
            FOR EACH STATEMENT EXECUTE FUNCTION protect_population_truncate()
            """
        )


def upgrade() -> None:
    """Create normalized population storage and database-enforced sealing."""
    _create_tables()
    _create_canonical_functions()
    _create_dataset_guards()
    _create_cohort_guards()
    _create_truncate_guards()


def downgrade() -> None:
    """Remove the MatrAIx population schema and its guard functions."""
    op.drop_table("cohort_members")
    op.drop_table("cohorts")
    op.drop_table("personas")
    op.drop_table("persona_datasets")
    op.execute("DROP FUNCTION IF EXISTS protect_population_truncate()")
    op.execute("DROP FUNCTION IF EXISTS protect_cohort_member_mutation()")
    op.execute("DROP FUNCTION IF EXISTS protect_cohort_update_delete()")
    op.execute("DROP FUNCTION IF EXISTS enforce_cohort_draft_insert()")
    op.execute("DROP FUNCTION IF EXISTS protect_persona_mutation()")
    op.execute("DROP FUNCTION IF EXISTS protect_persona_dataset_update_delete()")
    op.execute("DROP FUNCTION IF EXISTS enforce_persona_dataset_draft_insert()")
    op.execute("DROP FUNCTION IF EXISTS canonical_matraix_cohort_json(uuid)")
    op.execute("DROP FUNCTION IF EXISTS canonical_matraix_persona_dataset_json(uuid)")
    op.execute("DROP FUNCTION IF EXISTS canonical_matraix_persona_profile_json(uuid)")
