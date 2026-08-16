"""Freeze selected immutable Policy versions into World snapshots.

Revision ID: 20260816_core_0038
Revises: 20260816_core_0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0038"
down_revision: str | None = "20260816_core_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_canonical_snapshot_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION canonical_world_snapshot_json(target_snapshot_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected_snapshot world_snapshots%ROWTYPE;
            evidence_json text;
            policy_json text;
            policy_count bigint;
        BEGIN
            SELECT * INTO selected_snapshot
            FROM world_snapshots
            WHERE id = target_snapshot_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cannot canonicalize missing world snapshot %', target_snapshot_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT string_agg(
                '{"article_id":' || to_json(evidence.article_id::text)::text ||
                ',"captured_at":' || to_json(
                    to_char(
                        evidence.captured_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    )
                )::text ||
                ',"captured_text_sha256":' ||
                    to_json(evidence.captured_text_sha256)::text ||
                ',"country_code":' ||
                    coalesce(to_json(evidence.country_code)::text, 'null') ||
                ',"excerpt":' || to_json(evidence.excerpt)::text ||
                ',"original_url":' || to_json(evidence.original_url)::text ||
                ',"published_at":' || to_json(
                    to_char(
                        evidence.published_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    )
                )::text ||
                ',"source_name":' || to_json(evidence.source_name)::text ||
                ',"title":' || to_json(evidence.title)::text || '}',
                ',' ORDER BY evidence.position
            )
            INTO evidence_json
            FROM world_snapshot_evidence AS evidence
            WHERE evidence.snapshot_id = target_snapshot_id;

            SELECT count(*), string_agg(
                '{"authority_name":' || to_json(policy.authority_name)::text ||
                ',"canonical_identifier":' || to_json(policy.canonical_identifier)::text ||
                ',"captured_at":' || to_json(
                    to_char(
                        policy.captured_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    )
                )::text ||
                ',"content_sha256":' || to_json(policy.content_sha256)::text ||
                ',"document_sha256":' || to_json(policy.document_sha256)::text ||
                ',"effective_from":' ||
                    coalesce(to_json(policy.effective_from::text)::text, 'null') ||
                ',"effective_until":' ||
                    coalesce(to_json(policy.effective_until::text)::text, 'null') ||
                ',"homepage_url":' || to_json(policy.homepage_url)::text ||
                ',"jurisdiction_code":' || to_json(policy.jurisdiction_code)::text ||
                ',"language":' || to_json(policy.language)::text ||
                ',"original_url":' || to_json(policy.original_url)::text ||
                ',"policy_version_id":' || to_json(policy.policy_version_id::text)::text ||
                ',"publication_date":' || to_json(policy.publication_date::text)::text ||
                ',"source_sha256":' || to_json(policy.source_sha256)::text ||
                ',"title":' || to_json(policy.title)::text ||
                ',"version":' || policy.version::text ||
                ',"version_sha256":' || to_json(policy.version_sha256)::text || '}',
                ',' ORDER BY policy.position
            )
            INTO policy_count, policy_json
            FROM world_snapshot_policy_evidence AS policy
            WHERE policy.snapshot_id = target_snapshot_id;

            IF policy_count = 0 THEN
                RETURN '{"evidence":[' || coalesce(evidence_json, '') ||
                    '],"schema_version":"world-snapshot/v2"' ||
                    ',"verification":' || to_json(selected_snapshot.verification)::text ||
                    ',"version":' || selected_snapshot.version::text ||
                    ',"world_model_id":' ||
                        to_json(selected_snapshot.world_model_id::text)::text || '}';
            END IF;
            RETURN '{"evidence":[' || coalesce(evidence_json, '') ||
                '],"policy_evidence":[' || coalesce(policy_json, '') ||
                '],"schema_version":"world-snapshot/v3"' ||
                ',"verification":' || to_json(selected_snapshot.verification)::text ||
                ',"version":' || selected_snapshot.version::text ||
                ',"world_model_id":' ||
                    to_json(selected_snapshot.world_model_id::text)::text || '}';
        END;
        $$
        """
    )


def _replace_seal_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_world_snapshot_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            evidence_count bigint;
            first_evidence_position integer;
            last_evidence_position integer;
            policy_count bigint;
            first_policy_position integer;
            last_policy_position integer;
            invalid_evidence_position integer;
            invalid_policy_position integer;
            actual_snapshot_sha256 text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'world snapshot % is immutable; DELETE is forbidden', OLD.id
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.sealed_at IS NULL
               AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW) - 'sealed_at') =
                   (to_jsonb(OLD) - 'sealed_at')
            THEN
                SELECT count(*), min(position), max(position)
                INTO evidence_count, first_evidence_position, last_evidence_position
                FROM world_snapshot_evidence
                WHERE snapshot_id = NEW.id;
                SELECT count(*), min(position), max(position)
                INTO policy_count, first_policy_position, last_policy_position
                FROM world_snapshot_policy_evidence
                WHERE snapshot_id = NEW.id;

                IF evidence_count < 1
                   OR evidence_count > 50
                   OR first_evidence_position <> 0
                   OR last_evidence_position <> evidence_count - 1
                THEN
                    RAISE EXCEPTION
                        'world snapshot % cannot be sealed; media evidence must contain 1..50 '
                        'contiguous positions starting at zero', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                IF policy_count > 50
                   OR (policy_count > 0 AND (
                       first_policy_position <> 0
                       OR last_policy_position <> policy_count - 1
                   ))
                   OR evidence_count + policy_count > 50
                THEN
                    RAISE EXCEPTION
                        'world snapshot % cannot be sealed; Policy evidence positions must be '
                        'contiguous and total evidence cannot exceed 50', NEW.id
                        USING ERRCODE = '55000';
                END IF;

                SELECT evidence.position
                INTO invalid_evidence_position
                FROM world_snapshot_evidence AS evidence
                WHERE evidence.snapshot_id = NEW.id
                  AND encode(
                        sha256(convert_to(evidence.captured_text, 'UTF8')),
                        'hex'
                      ) IS DISTINCT FROM evidence.captured_text_sha256
                ORDER BY evidence.position
                LIMIT 1;
                IF FOUND THEN
                    RAISE EXCEPTION
                        'world snapshot % cannot be sealed; evidence position % '
                        'captured_text_sha256 mismatch', NEW.id, invalid_evidence_position
                        USING ERRCODE = '55000';
                END IF;

                SELECT policy.position
                INTO invalid_policy_position
                FROM world_snapshot_policy_evidence AS policy
                JOIN policy_document_versions AS version
                  ON version.id = policy.policy_version_id
                JOIN policy_documents AS document
                  ON document.id = version.document_id
                JOIN policy_sources AS source
                  ON source.id = document.source_id
                WHERE policy.snapshot_id = NEW.id
                  AND (
                    encode(sha256(convert_to(policy.captured_text, 'UTF8')), 'hex')
                        IS DISTINCT FROM policy.content_sha256
                    OR policy.authority_name IS DISTINCT FROM source.authority_name
                    OR policy.jurisdiction_code IS DISTINCT FROM source.jurisdiction_code
                    OR policy.homepage_url IS DISTINCT FROM source.homepage_url
                    OR policy.source_sha256 IS DISTINCT FROM source.source_sha256
                    OR policy.canonical_identifier IS DISTINCT FROM document.canonical_identifier
                    OR policy.document_sha256 IS DISTINCT FROM document.document_sha256
                    OR policy.version IS DISTINCT FROM version.version
                    OR policy.title IS DISTINCT FROM version.title
                    OR policy.original_url IS DISTINCT FROM version.original_url
                    OR policy.language IS DISTINCT FROM version.language
                    OR policy.publication_date IS DISTINCT FROM version.publication_date
                    OR policy.effective_from IS DISTINCT FROM version.effective_from
                    OR policy.effective_until IS DISTINCT FROM version.effective_until
                    OR policy.captured_at IS DISTINCT FROM version.captured_at
                    OR policy.captured_text IS DISTINCT FROM version.captured_text
                    OR policy.content_sha256 IS DISTINCT FROM version.content_sha256
                    OR policy.version_sha256 IS DISTINCT FROM version.version_sha256
                  )
                ORDER BY policy.position
                LIMIT 1;
                IF FOUND THEN
                    RAISE EXCEPTION
                        'world snapshot % cannot be sealed; Policy evidence position % '
                        'does not exactly match its immutable source version',
                        NEW.id, invalid_policy_position
                        USING ERRCODE = '55000';
                END IF;

                actual_snapshot_sha256 := encode(
                    sha256(convert_to(canonical_world_snapshot_json(NEW.id), 'UTF8')),
                    'hex'
                );
                IF actual_snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256 THEN
                    RAISE EXCEPTION
                        'world snapshot % cannot be sealed; snapshot_sha256 mismatch', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'world snapshot % is immutable; only sealing a complete draft is allowed', OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "world_snapshot_policy_evidence",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authority_name", sa.String(length=300), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=16), nullable=False),
        sa.Column("homepage_url", sa.String(length=1000), nullable=False),
        sa.Column("canonical_identifier", sa.String(length=256), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_url", sa.String(length=1000), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("version_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_world_snapshot_policy_position"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from",
            name="ck_world_snapshot_policy_effectivity",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[a-f0-9]{64}$' AND version_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_world_snapshot_policy_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["world_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "position"),
        sa.UniqueConstraint(
            "snapshot_id",
            "policy_version_id",
            name="uq_world_snapshot_policy_version",
        ),
    )
    op.create_index(
        "ix_world_snapshot_policy_version",
        "world_snapshot_policy_evidence",
        ["policy_version_id"],
    )
    op.execute(
        """
        CREATE TRIGGER trg_world_snapshot_policy_evidence_append_only
        BEFORE UPDATE OR DELETE ON world_snapshot_policy_evidence
        FOR EACH ROW EXECUTE FUNCTION reject_world_snapshot_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_world_snapshot_policy_evidence_draft_insert_only
        BEFORE INSERT ON world_snapshot_policy_evidence
        FOR EACH ROW EXECUTE FUNCTION protect_world_snapshot_child_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_world_snapshot_policy_evidence_reject_truncate
        BEFORE TRUNCATE ON world_snapshot_policy_evidence
        FOR EACH STATEMENT EXECUTE FUNCTION reject_world_snapshot_truncate()
        """
    )
    _replace_canonical_snapshot_function()
    _replace_seal_function()


def downgrade() -> None:
    op.execute(
        """DROP TRIGGER trg_world_snapshot_policy_evidence_reject_truncate
        ON world_snapshot_policy_evidence"""
    )
    op.execute(
        """DROP TRIGGER trg_world_snapshot_policy_evidence_draft_insert_only
        ON world_snapshot_policy_evidence"""
    )
    op.execute(
        """DROP TRIGGER trg_world_snapshot_policy_evidence_append_only
        ON world_snapshot_policy_evidence"""
    )
    op.drop_index(
        "ix_world_snapshot_policy_version",
        table_name="world_snapshot_policy_evidence",
    )
    op.drop_table("world_snapshot_policy_evidence")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION canonical_world_snapshot_json(target_snapshot_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE AS $$
        DECLARE selected_snapshot world_snapshots%ROWTYPE; evidence_json text;
        BEGIN
            SELECT * INTO selected_snapshot FROM world_snapshots WHERE id=target_snapshot_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'cannot canonicalize missing world snapshot %', target_snapshot_id
                    USING ERRCODE='55000';
            END IF;
            SELECT string_agg(
                '{"article_id":' || to_json(evidence.article_id::text)::text ||
                ',"captured_at":' || to_json(to_char(
                    evidence.captured_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                ))::text ||
                ',"captured_text_sha256":' || to_json(evidence.captured_text_sha256)::text ||
                ',"country_code":' || coalesce(to_json(evidence.country_code)::text,'null') ||
                ',"excerpt":' || to_json(evidence.excerpt)::text ||
                ',"original_url":' || to_json(evidence.original_url)::text ||
                ',"published_at":' || to_json(to_char(
                    evidence.published_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                ))::text ||
                ',"source_name":' || to_json(evidence.source_name)::text ||
                ',"title":' || to_json(evidence.title)::text || '}',
                ',' ORDER BY evidence.position
            ) INTO evidence_json FROM world_snapshot_evidence AS evidence
            WHERE evidence.snapshot_id=target_snapshot_id;
            RETURN '{"evidence":[' || coalesce(evidence_json,'') ||
                '],"schema_version":"world-snapshot/v2"' ||
                ',"verification":' || to_json(selected_snapshot.verification)::text ||
                ',"version":' || selected_snapshot.version::text ||
                ',"world_model_id":' ||
                    to_json(selected_snapshot.world_model_id::text)::text || '}';
        END; $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_world_snapshot_update_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE evidence_count bigint; first_evidence_position integer;
        last_evidence_position integer; invalid_evidence_position integer;
        actual_snapshot_sha256 text;
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'world snapshot % is immutable; DELETE is forbidden', OLD.id
                    USING ERRCODE='55000';
            END IF;
            IF OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW)-'sealed_at')=(to_jsonb(OLD)-'sealed_at') THEN
                SELECT count(*),min(position),max(position)
                INTO evidence_count,first_evidence_position,last_evidence_position
                FROM world_snapshot_evidence WHERE snapshot_id=NEW.id;
                IF evidence_count<1 OR evidence_count>50 OR first_evidence_position<>0
                   OR last_evidence_position<>evidence_count-1 THEN
                    RAISE EXCEPTION
                        'world snapshot % cannot be sealed; invalid evidence positions', NEW.id
                        USING ERRCODE='55000';
                END IF;
                SELECT evidence.position INTO invalid_evidence_position
                FROM world_snapshot_evidence AS evidence
                WHERE evidence.snapshot_id=NEW.id
                  AND encode(sha256(convert_to(evidence.captured_text,'UTF8')),'hex')
                      IS DISTINCT FROM evidence.captured_text_sha256
                ORDER BY evidence.position LIMIT 1;
                IF FOUND THEN
                    RAISE EXCEPTION
                        'world snapshot % evidence position % text hash mismatch',
                        NEW.id, invalid_evidence_position
                        USING ERRCODE='55000';
                END IF;
                actual_snapshot_sha256 := encode(sha256(convert_to(
                    canonical_world_snapshot_json(NEW.id), 'UTF8'
                )), 'hex');
                IF actual_snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256 THEN
                    RAISE EXCEPTION
                        'world snapshot % snapshot_sha256 mismatch', NEW.id
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION
                'world snapshot % only permits sealing a complete draft', OLD.id
                USING ERRCODE='55000';
        END; $$
        """
    )
