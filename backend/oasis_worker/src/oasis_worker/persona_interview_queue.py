"""PostgreSQL queue operations for report-grounded Persona interviews."""

import json
from datetime import datetime
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from oasis_worker.persona_interview_contracts import (
    ClaimedPersonaInterview,
    InterviewReportSection,
    NormalizedPersonaInterviewAnswer,
)
from oasis_worker.persona_interview_hashing import answer_sha256, interview_sha256
from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.semantic_contracts import PersonaProfile, SemanticRuntimeConfig
from oasis_worker.semantic_hashing import persona_profile_sha256


def persona_interview_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at FROM persona_report_interviews
            WHERE status='queued' AND model_name=%s AND semantic_config_sha256=%s
              AND prompt_schema_version='persona-report-interview/v1'
            ORDER BY created_at, id LIMIT 1
            """,
            (runtime_config.model_name, runtime_config.config_sha256),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row["id"], row["created_at"]


def claim_persona_interview(
    connection: Connection[dict[str, object]],
    interview_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedPersonaInterview | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT interview.*, report.title AS report_title,
                       report.report_sha256 AS actual_report_sha256,
                       cohort.cohort_sha256 AS actual_cohort_sha256,
                       member.position AS actual_persona_position,
                       persona.persona_id AS actual_persona_external_id,
                       persona.display_name AS actual_persona_display_name,
                       persona.profile_sha256 AS actual_persona_profile_sha256,
                       persona.profile_json
                FROM persona_report_interviews interview
                JOIN decision_reports report
                  ON report.id=interview.report_id AND report.sealed_at IS NOT NULL
                JOIN cohorts cohort
                  ON cohort.id=interview.cohort_id AND cohort.sealed_at IS NOT NULL
                JOIN cohort_members member
                  ON member.cohort_id=cohort.id AND member.persona_id=interview.persona_id
                JOIN personas persona ON persona.id=member.persona_id
                WHERE interview.id=%s AND interview.status='queued'
                  AND interview.model_name=%s AND interview.semantic_config_sha256=%s
                FOR UPDATE OF interview SKIP LOCKED
                """,
                (interview_id, runtime_config.model_name, runtime_config.config_sha256),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return None
            if (
                row["report_sha256"] != row["actual_report_sha256"]
                or row["cohort_sha256"] != row["actual_cohort_sha256"]
                or row["persona_position"] != row["actual_persona_position"]
                or row["persona_external_id"] != row["actual_persona_external_id"]
                or row["persona_display_name"] != row["actual_persona_display_name"]
                or row["persona_profile_sha256"] != row["actual_persona_profile_sha256"]
            ):
                raise RuntimeError("Persona interview frozen input mismatch")
            expected = interview_sha256(
                row["report_sha256"],
                row["cohort_sha256"],
                str(row["persona_id"]),
                row["persona_profile_sha256"],
                row["question"],
                row["semantic_config_sha256"],
            )
            if expected != row["interview_sha256"]:
                raise RuntimeError("Persona interview digest mismatch")
            cursor.execute(
                """
                SELECT position, kind, title, body_markdown
                FROM decision_report_sections WHERE report_id=%s ORDER BY position
                """,
                (row["report_id"],),
            )
            sections = tuple(
                InterviewReportSection(
                    position=item["position"],
                    kind=item["kind"],
                    title=item["title"],
                    body_markdown=item["body_markdown"],
                )
                for item in cursor.fetchall()
            )
            persona_profile = PersonaProfile.model_validate(row["profile_json"])
            if persona_profile_sha256(persona_profile) != row["persona_profile_sha256"]:
                raise RuntimeError("Persona interview profile content digest mismatch")
            job = ClaimedPersonaInterview(
                id=row["id"],
                report_id=row["report_id"],
                report_sha256=row["report_sha256"],
                cohort_id=row["cohort_id"],
                cohort_sha256=row["cohort_sha256"],
                persona_id=row["persona_id"],
                persona_position=row["persona_position"],
                persona_external_id=row["persona_external_id"],
                persona_display_name=row["persona_display_name"],
                persona_profile=persona_profile,
                persona_profile_sha256=row["persona_profile_sha256"],
                question=row["question"],
                interview_sha256=row["interview_sha256"],
                model_name=row["model_name"],
                semantic_config_sha256=row["semantic_config_sha256"],
                prompt_schema_version=row["prompt_schema_version"],
                created_at=row["created_at"],
                report_title=row["report_title"],
                report_sections=sections,
            )
            cursor.execute(
                """
                UPDATE persona_report_interviews
                SET status='running', started_at=now(), claimed_by_worker_id=%s
                WHERE id=%s AND status='queued'
                """,
                (worker_id, interview_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued Persona interview could not be claimed")
        connection.commit()
        return job
    except (ValidationError, RuntimeError, KeyError, TypeError) as error:
        connection.rollback()
        fail_persona_interview(
            connection,
            interview_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=(
                    "Persona interview queue integrity failed: " + " ".join(str(error).split())
                )[:500],
            ),
            True,
        )
        return None


def complete_persona_interview(
    connection: Connection[dict[str, object]],
    interview_id: UUID,
    worker_id: str,
    result: NormalizedPersonaInterviewAnswer,
) -> None:
    positions_json = json.dumps(result.cited_section_positions, separators=(",", ":"))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT interview_sha256 FROM persona_report_interviews
            WHERE id=%s AND status='running' AND claimed_by_worker_id=%s FOR UPDATE
            """,
            (interview_id, worker_id),
        )
        row = cursor.fetchone()
        if row is None or result.answer_sha256 != answer_sha256(
            row["interview_sha256"],
            result.answer_markdown,
            result.cited_section_positions,
        ):
            raise RuntimeError("Persona interview answer digest mismatch")
        cursor.execute(
            """
            UPDATE persona_report_interviews
            SET status='succeeded', completed_at=now(), answer_markdown=%s,
                cited_section_positions_json=%s, answer_sha256=%s
            WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
            """,
            (
                result.answer_markdown,
                positions_json,
                result.answer_sha256,
                interview_id,
                worker_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("running Persona interview could not be completed")
    connection.commit()


def fail_persona_interview(
    connection: Connection[dict[str, object]],
    interview_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
    claim_first: bool,
) -> None:
    with connection.cursor() as cursor:
        if claim_first:
            cursor.execute(
                """
                UPDATE persona_report_interviews
                SET status='running', started_at=now(), claimed_by_worker_id=%s
                WHERE id=%s AND status='queued'
                """,
                (worker_id, interview_id),
            )
        cursor.execute(
            """
            UPDATE persona_report_interviews
            SET status='failed', completed_at=now(), error_code=%s, error_message=%s
            WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
            """,
            (failure.code, failure.message, interview_id, worker_id),
        )
    connection.commit()


def fail_persona_interviews_owned_by_worker(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE persona_report_interviews
            SET status='failed', completed_at=now(), error_code='worker_process_restarted',
                error_message='The model worker restarted before completing this interview.'
            WHERE status='running' AND claimed_by_worker_id=%s
            """,
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_persona_interviews(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Persona interview orphan cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE persona_report_interviews AS interview
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_expired',
                error_message='The model worker heartbeat expired before completing this interview.'
            WHERE interview.status='running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats heartbeat
                WHERE heartbeat.worker_id=interview.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff,),
        )
        count = cursor.rowcount
    connection.commit()
    return count
