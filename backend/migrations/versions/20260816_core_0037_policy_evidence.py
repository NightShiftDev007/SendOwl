"""Create immutable Policy evidence sources and document versions.

Revision ID: 20260816_core_0037
Revises: 20260816_core_0036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0037"
down_revision: str | None = "20260816_core_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authority_name", sa.String(length=300), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=16), nullable=False),
        sa.Column("homepage_url", sa.String(length=1000), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "authority_name=btrim(authority_name) AND length(authority_name) BETWEEN 1 AND 300",
            name="ck_policy_source_authority",
        ),
        sa.CheckConstraint(
            "jurisdiction_code ~ '^[A-Z0-9][A-Z0-9-]{1,15}$'",
            name="ck_policy_source_jurisdiction",
        ),
        sa.CheckConstraint(
            "homepage_url ~ '^https?://' AND length(homepage_url) <= 1000",
            name="ck_policy_source_homepage",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_policy_source_sha",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_sha256", name="uq_policy_source_sha"),
    )
    op.create_table(
        "policy_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_identifier", sa.String(length=256), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "canonical_identifier=btrim(canonical_identifier) "
            "AND length(canonical_identifier) BETWEEN 1 AND 256",
            name="ck_policy_document_identifier",
        ),
        sa.CheckConstraint(
            "document_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_policy_document_sha",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["policy_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_sha256", name="uq_policy_document_sha"),
        sa.UniqueConstraint(
            "source_id",
            "canonical_identifier",
            name="uq_policy_document_source_identifier",
        ),
    )
    op.create_table(
        "policy_document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_url", sa.String(length=1000), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification", sa.String(length=32), nullable=False),
        sa.Column("captured_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("version_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("version BETWEEN 1 AND 100", name="ck_policy_version_position"),
        sa.CheckConstraint(
            "title=btrim(title) AND length(title) BETWEEN 1 AND 500",
            name="ck_policy_version_title",
        ),
        sa.CheckConstraint(
            "original_url ~ '^https?://' AND length(original_url) <= 1000",
            name="ck_policy_version_url",
        ),
        sa.CheckConstraint(
            "language ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="ck_policy_version_language",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from",
            name="ck_policy_version_effectivity",
        ),
        sa.CheckConstraint(
            "verification='human_confirmed'",
            name="ck_policy_version_verification",
        ),
        sa.CheckConstraint(
            "length(captured_text) BETWEEN 1 AND 2000000 AND captured_text ~ '[^[:space:]]'",
            name="ck_policy_version_content",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_policy_version_content_sha",
        ),
        sa.CheckConstraint(
            "version_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_policy_version_sha",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["policy_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_sha256", name="uq_policy_version_sha"),
        sa.UniqueConstraint(
            "document_id",
            "version",
            name="uq_policy_version_document_position",
        ),
    )
    op.create_index(
        "ix_policy_versions_publication_date",
        "policy_document_versions",
        ["publication_date"],
    )
    op.create_index(
        "ix_policy_versions_effective_from",
        "policy_document_versions",
        ["effective_from"],
    )
    op.execute(
        """
        CREATE FUNCTION policy_digest(parts text[])
        RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT AS $$
        DECLARE payload bytea := ''::bytea;
        DECLARE item text;
        DECLARE first_item boolean := true;
        BEGIN
            FOREACH item IN ARRAY parts LOOP
                IF item IS NULL THEN
                    RAISE EXCEPTION 'Policy digest parts cannot be null'
                        USING ERRCODE='22023';
                END IF;
                IF NOT first_item THEN payload := payload || decode('00', 'hex'); END IF;
                payload := payload || convert_to(item, 'UTF8');
                first_item := false;
            END LOOP;
            RETURN encode(digest(payload, 'sha256'), 'hex');
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_policy_evidence()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent policy_documents%ROWTYPE;
        DECLARE source policy_sources%ROWTYPE;
        DECLARE expected text;
        DECLARE stored_count integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Policy evidence is immutable' USING ERRCODE='55000';
            END IF;
            IF TG_TABLE_NAME='policy_sources' THEN
                expected := policy_digest(ARRAY[
                    'policy-source/v1', NEW.authority_name,
                    NEW.jurisdiction_code, NEW.homepage_url
                ]);
                IF NEW.source_sha256 IS DISTINCT FROM expected THEN
                    RAISE EXCEPTION 'Policy source hash mismatch' USING ERRCODE='55000';
                END IF;
            ELSIF TG_TABLE_NAME='policy_documents' THEN
                SELECT * INTO source FROM policy_sources WHERE id=NEW.source_id FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Policy document source is missing' USING ERRCODE='55000';
                END IF;
                expected := policy_digest(ARRAY[
                    'policy-document/v1', source.source_sha256, NEW.canonical_identifier
                ]);
                IF NEW.document_sha256 IS DISTINCT FROM expected THEN
                    RAISE EXCEPTION 'Policy document hash mismatch' USING ERRCODE='55000';
                END IF;
            ELSE
                SELECT * INTO parent FROM policy_documents
                WHERE id=NEW.document_id FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Policy version document is missing' USING ERRCODE='55000';
                END IF;
                SELECT count(*) INTO stored_count FROM policy_document_versions
                WHERE document_id=NEW.document_id;
                IF NEW.version <> stored_count+1 THEN
                    RAISE EXCEPTION 'Policy versions must be contiguous' USING ERRCODE='55000';
                END IF;
                IF NEW.content_sha256 IS DISTINCT FROM
                   encode(digest(convert_to(NEW.captured_text, 'UTF8'), 'sha256'), 'hex') THEN
                    RAISE EXCEPTION 'Policy content hash mismatch' USING ERRCODE='55000';
                END IF;
                expected := policy_digest(ARRAY[
                    'policy-document-version/v1', parent.document_sha256,
                    NEW.title, NEW.original_url, NEW.language,
                    NEW.publication_date::text,
                    coalesce(NEW.effective_from::text, ''),
                    coalesce(NEW.effective_until::text, ''), NEW.content_sha256
                ]);
                IF NEW.version_sha256 IS DISTINCT FROM expected THEN
                    RAISE EXCEPTION 'Policy version hash mismatch' USING ERRCODE='55000';
                END IF;
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    for table in ("policy_sources", "policy_documents", "policy_document_versions"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_protect BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_policy_evidence()"
        )
    op.execute(
        """
        CREATE FUNCTION reject_policy_evidence_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Policy evidence TRUNCATE is forbidden' USING ERRCODE='55000';
        END; $$
        """
    )
    for table in ("policy_sources", "policy_documents", "policy_document_versions"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION reject_policy_evidence_truncate()"
        )


def downgrade() -> None:
    for table in ("policy_document_versions", "policy_documents", "policy_sources"):
        op.execute(f"DROP TRIGGER trg_{table}_truncate ON {table}")
        op.execute(f"DROP TRIGGER trg_{table}_protect ON {table}")
    op.execute("DROP FUNCTION reject_policy_evidence_truncate()")
    op.execute("DROP FUNCTION protect_policy_evidence()")
    op.execute("DROP FUNCTION policy_digest(text[])")
    op.drop_index("ix_policy_versions_effective_from", table_name="policy_document_versions")
    op.drop_index("ix_policy_versions_publication_date", table_name="policy_document_versions")
    op.drop_table("policy_document_versions")
    op.drop_table("policy_documents")
    op.drop_table("policy_sources")
