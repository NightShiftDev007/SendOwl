"""Validate adopted core snapshots and enforce complete drafts before sealing.

Revision ID: 20260812_core_0005
Revises: 20260812_core_0004
Create Date: 2026-08-12
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection, RowMapping

revision: str = "20260812_core_0005"
down_revision: str | None = "20260812_core_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SNAPSHOT_SCHEMA_VERSION = "world-snapshot/v2"


@dataclass(frozen=True, slots=True)
class _StoredEvidence:
    position: int
    article_id: str
    source_name: str
    original_url: str
    title: str
    captured_text: str
    published_at: datetime
    captured_at: datetime
    country_code: str | None
    excerpt: str
    captured_text_sha256: str


@dataclass(frozen=True, slots=True)
class _StoredSnapshot:
    id: str
    world_model_id: str
    version: int
    verification: str
    snapshot_sha256: str
    sealed_at: datetime | None
    evidence: tuple[_StoredEvidence, ...]


def _canonical_timestamp(value: datetime) -> str:
    """Match the application snapshot timestamp representation exactly."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot timestamps must include a timezone offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_snapshot_json(snapshot: _StoredSnapshot) -> str:
    """Rebuild the exact generic canonical JSON used by world-model hashing."""
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "world_model_id": snapshot.world_model_id,
        "version": snapshot.version,
        "verification": snapshot.verification,
        "evidence": [
            {
                "article_id": evidence.article_id,
                "source_name": evidence.source_name,
                "original_url": evidence.original_url,
                "title": evidence.title,
                "published_at": _canonical_timestamp(evidence.published_at),
                "captured_at": _canonical_timestamp(evidence.captured_at),
                "country_code": evidence.country_code,
                "excerpt": evidence.excerpt,
                "captured_text_sha256": evidence.captured_text_sha256,
            }
            for evidence in snapshot.evidence
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _evidence_from_row(row: RowMapping) -> _StoredEvidence:
    published_at = row["published_at"]
    captured_at = row["captured_at"]
    if not isinstance(published_at, datetime) or not isinstance(captured_at, datetime):
        raise TypeError("stored snapshot evidence timestamps must be datetime values")
    country_code_value = row["country_code"]
    return _StoredEvidence(
        position=int(row["position"]),
        article_id=str(row["article_id"]),
        source_name=str(row["source_name"]),
        original_url=str(row["original_url"]),
        title=str(row["title"]),
        captured_text=str(row["captured_text"]),
        published_at=published_at,
        captured_at=captured_at,
        country_code=None if country_code_value is None else str(country_code_value),
        excerpt=str(row["excerpt"]),
        captured_text_sha256=str(row["captured_text_sha256"]),
    )


def _snapshot_from_row(
    row: RowMapping,
    evidence: tuple[_StoredEvidence, ...],
) -> _StoredSnapshot:
    sealed_at_value = row["sealed_at"]
    if sealed_at_value is not None and not isinstance(sealed_at_value, datetime):
        raise TypeError("stored snapshot sealed_at must be a datetime value or NULL")
    return _StoredSnapshot(
        id=str(row["id"]),
        world_model_id=str(row["world_model_id"]),
        version=int(row["version"]),
        verification=str(row["verification"]),
        snapshot_sha256=str(row["snapshot_sha256"]),
        sealed_at=sealed_at_value,
        evidence=evidence,
    )


def _load_existing_snapshots(connection: Connection) -> tuple[_StoredSnapshot, ...]:
    evidence_rows = (
        connection.execute(
            sa.text(
                """
                SELECT snapshot_id, position, article_id, source_name, original_url,
                       title, captured_text, published_at, captured_at, country_code,
                       excerpt, captured_text_sha256
                FROM world_snapshot_evidence
                ORDER BY snapshot_id, position
                """
            )
        )
        .mappings()
        .all()
    )
    evidence_by_snapshot: dict[str, list[_StoredEvidence]] = {}
    for row in evidence_rows:
        snapshot_id = str(row["snapshot_id"])
        evidence_by_snapshot.setdefault(snapshot_id, []).append(_evidence_from_row(row))

    snapshot_rows = (
        connection.execute(
            sa.text(
                """
                SELECT id, world_model_id, version, verification, snapshot_sha256, sealed_at
                FROM world_snapshots
                ORDER BY id
                """
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        _snapshot_from_row(
            row,
            tuple(evidence_by_snapshot.get(str(row["id"]), ())),
        )
        for row in snapshot_rows
    )


def _snapshot_integrity_issues(snapshot: _StoredSnapshot) -> tuple[str, ...]:
    issues: list[str] = []
    if snapshot.sealed_at is None:
        issues.append("snapshot is an unsealed persisted draft")

    evidence_count = len(snapshot.evidence)
    if not 1 <= evidence_count <= 50:
        issues.append(f"evidence count {evidence_count} is outside [1, 50]")
    evidence_positions = tuple(item.position for item in snapshot.evidence)
    if evidence_positions != tuple(range(evidence_count)):
        issues.append(f"evidence positions are not contiguous: {evidence_positions}")

    for evidence in snapshot.evidence:
        actual_text_digest = sha256(evidence.captured_text.encode("utf-8")).hexdigest()
        if actual_text_digest != evidence.captured_text_sha256:
            issues.append(f"evidence position {evidence.position} captured_text_sha256 mismatch")

    actual_snapshot_digest = sha256(_canonical_snapshot_json(snapshot).encode("utf-8")).hexdigest()
    if actual_snapshot_digest != snapshot.snapshot_sha256:
        issues.append("snapshot_sha256 mismatch")
    return tuple(issues)


def _preflight_existing_snapshots(connection: Connection) -> None:
    """Abort before installing new guards if revision core_0004 adopted corrupt data."""
    invalid: list[tuple[str, tuple[str, ...]]] = []
    for snapshot in _load_existing_snapshots(connection):
        issues = _snapshot_integrity_issues(snapshot)
        if issues:
            invalid.append((snapshot.id, issues))
    if invalid:
        details = "; ".join(
            f"{snapshot_id} ({', '.join(issues)})" for snapshot_id, issues in invalid
        )
        raise RuntimeError(
            "world snapshot integrity preflight failed; migration 20260812_core_0005 "
            f"aborted; invalid snapshot IDs: {details}"
        )


def _create_canonical_snapshot_function() -> None:
    """Install a SQL equivalent of the application's canonical JSON encoder."""
    op.execute(
        """
        CREATE FUNCTION canonical_world_snapshot_json(target_snapshot_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected_snapshot world_snapshots%ROWTYPE;
            evidence_json text;
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

            RETURN '{"evidence":[' || coalesce(evidence_json, '') ||
                '],"schema_version":"world-snapshot/v2"' ||
                ',"verification":' || to_json(selected_snapshot.verification)::text ||
                ',"version":' || selected_snapshot.version::text ||
                ',"world_model_id":' ||
                    to_json(selected_snapshot.world_model_id::text)::text || '}';
        END;
        $$
        """
    )


def upgrade() -> None:
    """Validate adopted rows, then require exact generic evidence at every seal."""
    connection = op.get_bind()
    op.execute("LOCK TABLE world_snapshots, world_snapshot_evidence IN ACCESS EXCLUSIVE MODE")
    _preflight_existing_snapshots(connection)
    _create_canonical_snapshot_function()

    op.execute(
        """
        CREATE FUNCTION enforce_world_snapshot_draft_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'world snapshot % must be inserted as an unsealed draft', NEW.id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_world_snapshots_draft_insert_only
        BEFORE INSERT ON world_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION enforce_world_snapshot_draft_insert()
        """
    )

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
            invalid_evidence_position integer;
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

                IF evidence_count < 1
                   OR evidence_count > 50
                   OR first_evidence_position <> 0
                   OR last_evidence_position <> evidence_count - 1
                THEN
                    RAISE EXCEPTION
                        'world snapshot % cannot be sealed; evidence must contain 1..50 '
                        'contiguous positions starting at zero', NEW.id
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
                'world snapshot % is immutable; only sealing a complete draft is allowed',
                OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )


def downgrade() -> None:
    """Remove core_0005 guards and restore core_0004 exactly."""
    op.execute("DROP TRIGGER trg_world_snapshots_draft_insert_only ON world_snapshots")
    op.execute("DROP FUNCTION enforce_world_snapshot_draft_insert()")
    op.execute("DROP FUNCTION canonical_world_snapshot_json(uuid)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_world_snapshot_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
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
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'world snapshot % is immutable; only sealing a draft is allowed', OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
