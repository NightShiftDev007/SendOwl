"""PostgreSQL queue for interviews over one frozen research run."""

# ruff: noqa: E501

import json
from datetime import datetime
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.research_interview_contracts import (
    ClaimedResearchPersonaInterview,
    NormalizedResearchPersonaInterviewAnswer,
)
from oasis_worker.research_interview_hashing import (
    answer_sha256,
    interview_sha256,
    source_sha256,
)
from oasis_worker.semantic_contracts import PersonaProfile, SemanticRuntimeConfig
from oasis_worker.semantic_hashing import persona_profile_sha256


def research_interview_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at FROM research_run_persona_interviews
            WHERE status='queued' AND model_name=%s AND semantic_config_sha256=%s
              AND prompt_schema_version='sandowl-run-persona-interview/v1'
            ORDER BY created_at, id LIMIT 1
            """,
            (runtime_config.model_name, runtime_config.config_sha256),
        )
        row = cursor.fetchone()
    return None if row is None else (row["id"], row["created_at"])


def claim_research_interview(
    connection: Connection[dict[str, object]],
    interview_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedResearchPersonaInterview | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT interview.*,
                       run.run_spec_sha256 AS actual_run_spec_sha256,
                       run.cohort_sha256 AS actual_run_cohort_sha256,
                       memory.memory_sha256 AS actual_memory_sha256,
                       cohort.cohort_sha256 AS actual_cohort_sha256,
                       member.position AS actual_persona_position,
                       persona.persona_id AS actual_persona_external_id,
                       persona.display_name AS actual_persona_display_name,
                       persona.profile_sha256 AS actual_profile_sha256,
                       persona.profile_json
                FROM research_run_persona_interviews interview
                JOIN research_simulation_runs run
                  ON run.id=interview.research_simulation_run_id
                 AND run.research_project_id=interview.research_project_id
                 AND run.status='succeeded'
                 AND run.schema_version='sandowl-research-simulation-run/v4'
                JOIN research_run_graph_memory memory
                  ON memory.run_id=run.id AND memory.memory_sha256=interview.graph_memory_sha256
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
                row["run_spec_sha256"] != row["actual_run_spec_sha256"]
                or row["graph_memory_sha256"] != row["actual_memory_sha256"]
                or row["cohort_sha256"] != row["actual_cohort_sha256"]
                or row["cohort_sha256"] != row["actual_run_cohort_sha256"]
                or row["persona_position"] != row["actual_persona_position"]
                or row["persona_external_id"] != row["actual_persona_external_id"]
                or row["persona_display_name"] != row["actual_persona_display_name"]
                or row["persona_profile_sha256"] != row["actual_profile_sha256"]
                or source_sha256(row["source_text"]) != row["source_sha256"]
            ):
                raise RuntimeError("research Persona interview frozen input mismatch")
            profile = PersonaProfile.model_validate(row["profile_json"])
            if persona_profile_sha256(profile) != row["persona_profile_sha256"]:
                raise RuntimeError("research Persona interview profile digest mismatch")
            expected = interview_sha256(
                row["run_spec_sha256"],
                row["graph_memory_sha256"],
                row["cohort_sha256"],
                str(row["persona_id"]),
                row["persona_profile_sha256"],
                row["question"],
                row["source_sha256"],
                row["semantic_config_sha256"],
            )
            if expected != row["interview_sha256"]:
                raise RuntimeError("research Persona interview content digest mismatch")
            job = ClaimedResearchPersonaInterview(
                id=row["id"],
                research_project_id=row["research_project_id"],
                research_simulation_run_id=row["research_simulation_run_id"],
                run_spec_sha256=row["run_spec_sha256"],
                graph_memory_sha256=row["graph_memory_sha256"],
                cohort_id=row["cohort_id"],
                cohort_sha256=row["cohort_sha256"],
                persona_id=row["persona_id"],
                persona_position=row["persona_position"],
                persona_external_id=row["persona_external_id"],
                persona_display_name=row["persona_display_name"],
                persona_profile=profile,
                persona_profile_sha256=row["persona_profile_sha256"],
                question=row["question"],
                source_text=row["source_text"],
                source_sha256=row["source_sha256"],
                interview_sha256=row["interview_sha256"],
                model_name=row["model_name"],
                semantic_config_sha256=row["semantic_config_sha256"],
                prompt_schema_version=row["prompt_schema_version"],
                created_at=row["created_at"],
            )
            cursor.execute(
                "UPDATE research_run_persona_interviews SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, interview_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued research Persona interview could not be claimed")
        connection.commit()
        return job
    except (ValidationError, RuntimeError, KeyError, TypeError) as error:
        connection.rollback()
        fail_research_interview(
            connection,
            interview_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=(
                    "Research Persona interview integrity failed: " + " ".join(str(error).split())
                )[:500],
            ),
            True,
        )
        return None


def complete_research_interview(
    connection: Connection[dict[str, object]],
    interview_id: UUID,
    worker_id: str,
    result: NormalizedResearchPersonaInterviewAnswer,
) -> None:
    citations_json = json.dumps(
        [item.model_dump(mode="json") for item in result.citations],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT interview_sha256, research_simulation_run_id, source_text FROM research_run_persona_interviews WHERE id=%s AND status='running' AND claimed_by_worker_id=%s FOR UPDATE",
            (interview_id, worker_id),
        )
        row = cursor.fetchone()
        if row is None or result.answer_sha256 != answer_sha256(
            row["interview_sha256"], result.answer_markdown, result.citations
        ):
            raise RuntimeError("research Persona interview answer digest mismatch")
        if any(
            item.target_id != row["research_simulation_run_id"]
            or row["source_text"][item.start_offset : item.end_offset] != item.quote
            for item in result.citations
        ):
            raise RuntimeError("research Persona interview citation mismatch")
        cursor.execute(
            "UPDATE research_run_persona_interviews SET status='succeeded', completed_at=now(), answer_markdown=%s, citations_json=%s, answer_sha256=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (result.answer_markdown, citations_json, result.answer_sha256, interview_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("running research Persona interview could not be completed")
    connection.commit()


def fail_research_interview(
    connection: Connection[dict[str, object]],
    interview_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
    claim_if_queued: bool,
) -> None:
    with connection.cursor() as cursor:
        if claim_if_queued:
            cursor.execute(
                "UPDATE research_run_persona_interviews SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, interview_id),
            )
        cursor.execute(
            "UPDATE research_run_persona_interviews SET status='failed', completed_at=now(), error_code=%s, error_message=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (failure.code, failure.message, interview_id, worker_id),
        )
    connection.commit()


def fail_research_interviews_owned_by_worker(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_run_persona_interviews SET status='failed', completed_at=now(), error_code='worker_process_restarted', error_message='The report worker restarted before completing this run-grounded interview.' WHERE status='running' AND claimed_by_worker_id=%s",
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_research_interviews(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("research Persona interview cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE research_run_persona_interviews AS interview
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_expired',
                error_message='The report worker heartbeat expired before completing this run-grounded interview.'
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
