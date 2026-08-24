"""Claim and transition operations for native SandOwl research runs."""

import json
from collections.abc import Sequence
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from psycopg import Connection

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.research_contracts import (
    ClaimedResearchRun,
    ResearchRunGraphMemoryState,
    ResearchSimulationContext,
    ResearchSimulationPlan,
)
from oasis_worker.research_hashing import (
    context_bound_research_run_spec_sha256,
    legacy_research_run_spec_sha256,
    planned_research_run_spec_sha256,
    research_run_report_sha256,
    research_run_spec_sha256,
    simulation_context_sha256,
    simulation_plan_sha256,
)
from oasis_worker.research_memory import build_graph_memory, graph_memory_sha256
from oasis_worker.semantic_contracts import (
    CohortIntegrityInput,
    SemanticEvent,
    SemanticIntervention,
    SemanticRuntimeConfig,
    SemanticSuccess,
    SocialSimulationExecution,
)
from oasis_worker.semantic_queue import load_dataset_and_cohort


def research_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at
            FROM research_simulation_runs
            WHERE status = 'queued' AND model_name = %s
              AND semantic_config_sha256 = %s AND prompt_schema_version = %s
            ORDER BY created_at, id LIMIT 1
            """,
            (
                runtime_config.model_name,
                runtime_config.config_sha256,
                runtime_config.prompt_schema_version,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    if not isinstance(row["id"], UUID) or not isinstance(row["created_at"], datetime):
        raise RuntimeError("research queue head contains invalid PostgreSQL values")
    return row["id"], row["created_at"]


def _render_simulation_context(context: ResearchSimulationContext) -> str:
    media = "\n".join(
        f"- [{item.source_name}] {item.title}: {item.excerpt}" for item in context.media_items
    )
    policies = (
        "\n".join(
            f"- [{item.authority_name} / {item.jurisdiction_code}] {item.title}"
            for item in context.policy_items
        )
        or "- None selected"
    )
    entities = "\n".join(
        f"- {item.name} ({item.entity_type}): {item.summary} Evidence: {item.evidence_quote}"
        for item in context.nodes
    )
    relations = (
        "\n".join(
            f"- {item.source_name} --{item.relation_type}--> {item.target_name}: {item.fact} "
            f"Evidence: {item.evidence_quote}"
            for item in context.edges
        )
        or "- No evidence-backed relation was extracted"
    )
    return (
        "FROZEN REALITY CONTEXT (evidence-backed background, not a prediction):\n"
        f"Media evidence:\n{media}\n\nPolicy evidence:\n{policies}\n\n"
        f"Entities:\n{entities}\n\nRelations:\n{relations}"
    )


def _execution_from_row(
    row: dict[str, object],
    cohort: CohortIntegrityInput,
    simulation_context: ResearchSimulationContext | None,
    simulation_plan: ResearchSimulationPlan | None,
) -> SocialSimulationExecution:
    run_id = row["id"]
    project_id = row["research_project_id"]
    if not isinstance(run_id, UUID) or not isinstance(project_id, UUID):
        raise RuntimeError("research run identity is not a PostgreSQL UUID")
    if cohort.cohort_sha256 != row["cohort_sha256"]:
        raise RuntimeError("research run cohort digest does not match its frozen run design")
    if cohort.persona_count != row["persona_count"]:
        raise RuntimeError("research run cohort size does not match its frozen run design")
    initial_posts = (
        tuple(
            SemanticIntervention(
                id=uuid5(NAMESPACE_URL, f"sandowl:{run_id}:scheduled-post:{item.position}"),
                position=item.position,
                kind="initial_post",
                actor="scenario_actor",
                channel="reddit",
                content=item.content,
                offset_minutes=item.offset_minutes,
            )
            for item in simulation_plan.scheduled_posts
        )
        if simulation_plan is not None
        else (
            SemanticIntervention(
                id=uuid5(NAMESPACE_URL, f"sandowl:{run_id}:initial-post"),
                position=0,
                kind="initial_post",
                actor="scenario_actor",
                channel="reddit",
                content=str(row["initial_post"]),
                offset_minutes=0,
            ),
        )
    )
    context_text = (
        f"\n\n{_render_simulation_context(simulation_context)}"
        if simulation_context is not None
        else ""
    )
    return SocialSimulationExecution(
        id=run_id,
        context_id=project_id,
        context_kind="research_project",
        decision_question=(
            f"{row['research_question']}\n\nSimulation requirement:\n"
            f"{row['simulation_requirement']}{context_text}"
        ),
        actor_user_name=f"context_{run_id.hex[:16]}",
        actor_name="SandOwl 研究情境",
        actor_bio=f"Synthetic context actor for sealed SandOwl research project {project_id}.",
        seed=int(row["seed"]),
        rounds=int(row["rounds"]),
        minutes_per_round=int(row["minutes_per_round"]),
        model_name=str(row["model_name"]),
        semantic_config_sha256=str(row["semantic_config_sha256"]),
        prompt_schema_version=str(row["prompt_schema_version"]),
        initial_posts=initial_posts,
        cohort=cohort,
    )


def claim_research_run(
    connection: Connection[dict[str, object]],
    run_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedResearchRun | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT run.*, project.research_question, project.world_snapshot_id,
                   project.snapshot_sha256, project.world_graph_id,
                   project.graph_sha256, project.graph_node_count, project.graph_edge_count
            FROM research_simulation_runs AS run
            JOIN research_projects AS project ON project.id = run.research_project_id
            WHERE run.id = %s AND run.status = 'queued'
              AND run.model_name = %s AND run.semantic_config_sha256 = %s
              AND run.prompt_schema_version = %s
            FOR UPDATE OF run SKIP LOCKED
            """,
            (
                run_id,
                runtime_config.model_name,
                runtime_config.config_sha256,
                runtime_config.prompt_schema_version,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            connection.commit()
            return None
        cursor.execute(
            "SELECT snapshot_sha256 FROM world_snapshots WHERE id = %s AND sealed_at IS NOT NULL",
            (row["world_snapshot_id"],),
        )
        snapshot = cursor.fetchone()
        if snapshot is None or snapshot["snapshot_sha256"] != row["snapshot_sha256"]:
            raise RuntimeError("research run references an invalid sealed WorldSnapshot")
        cursor.execute(
            "SELECT count(*) AS count FROM world_snapshot_evidence WHERE snapshot_id = %s",
            (row["world_snapshot_id"],),
        )
        evidence = cursor.fetchone()
        if evidence is None or int(evidence["count"]) < 1:
            raise RuntimeError("research run WorldSnapshot contains no media evidence")
        _dataset, cohort = load_dataset_and_cohort(cursor, {"cohort_id": row["cohort_id"]})
        simulation_context = None
        simulation_plan = None
        if row["schema_version"] in (
            "sandowl-research-simulation-run/v3",
            "sandowl-research-simulation-run/v4",
        ):
            simulation_context = ResearchSimulationContext.model_validate_json(
                json.dumps(row["simulation_context"], ensure_ascii=False, allow_nan=False),
                strict=True,
            )
            actual_context_sha256 = simulation_context_sha256(
                simulation_context.model_dump(mode="json")
            )
            if actual_context_sha256 != row["simulation_context_sha256"]:
                raise RuntimeError("research run simulation context hash mismatch")
            if (
                simulation_context.snapshot_sha256 != row["snapshot_sha256"]
                or simulation_context.graph.graph_id != row["world_graph_id"]
                or simulation_context.graph.graph_sha256 != row["graph_sha256"]
                or simulation_context.graph.node_count != row["graph_node_count"]
                or simulation_context.graph.edge_count != row["graph_edge_count"]
            ):
                raise RuntimeError("research run simulation context does not match its project")
        if row["schema_version"] == "sandowl-research-simulation-run/v4":
            simulation_plan = ResearchSimulationPlan.model_validate_json(
                json.dumps(row["simulation_plan"], ensure_ascii=False, allow_nan=False),
                strict=True,
            )
            actual_plan_sha256 = simulation_plan_sha256(simulation_plan.model_dump(mode="json"))
            if actual_plan_sha256 != row["simulation_plan_sha256"]:
                raise RuntimeError("research run simulation plan hash mismatch")
            if (
                simulation_plan.rounds != row["rounds"]
                or simulation_plan.minutes_per_round != row["minutes_per_round"]
                or simulation_plan.scheduled_posts[0].content != row["initial_post"]
                or simulation_plan.persona_count != cohort.persona_count
                or simulation_plan.context_item_count
                != (
                    simulation_context.total_media_count
                    + simulation_context.total_policy_count
                    + simulation_context.total_node_count
                    + simulation_context.total_edge_count
                )
            ):
                raise RuntimeError("research run simulation plan does not match its run columns")
        execution = _execution_from_row(row, cohort, simulation_context, simulation_plan)
        if row["schema_version"] == "sandowl-research-simulation-run/v1":
            expected_spec = legacy_research_run_spec_sha256(
                str(row["project_sha256"]),
                int(row["seed"]),
                int(row["rounds"]),
                int(row["minutes_per_round"]),
                str(row["initial_post"]),
                str(row["model_name"]),
                str(row["semantic_config_sha256"]),
            )
        elif row["schema_version"] == "sandowl-research-simulation-run/v2":
            expected_spec = research_run_spec_sha256(
                str(row["project_sha256"]),
                str(row["cohort_id"]),
                str(row["cohort_sha256"]),
                int(row["persona_count"]),
                str(row["simulation_requirement"]),
                int(row["seed"]),
                int(row["rounds"]),
                int(row["minutes_per_round"]),
                str(row["initial_post"]),
                str(row["model_name"]),
                str(row["semantic_config_sha256"]),
            )
        elif row["schema_version"] == "sandowl-research-simulation-run/v3":
            expected_spec = context_bound_research_run_spec_sha256(
                str(row["project_sha256"]),
                str(row["cohort_id"]),
                str(row["cohort_sha256"]),
                int(row["persona_count"]),
                str(row["simulation_requirement"]),
                int(row["seed"]),
                int(row["rounds"]),
                int(row["minutes_per_round"]),
                str(row["initial_post"]),
                str(row["model_name"]),
                str(row["semantic_config_sha256"]),
                str(row["simulation_context_sha256"]),
            )
        elif row["schema_version"] == "sandowl-research-simulation-run/v4":
            expected_spec = planned_research_run_spec_sha256(
                str(row["project_sha256"]),
                str(row["cohort_id"]),
                str(row["cohort_sha256"]),
                int(row["persona_count"]),
                str(row["simulation_requirement"]),
                int(row["seed"]),
                str(row["model_name"]),
                str(row["semantic_config_sha256"]),
                str(row["simulation_context_sha256"]),
                str(row["simulation_plan_sha256"]),
            )
        else:
            raise RuntimeError("research run uses an unsupported schema version")
        if expected_spec != row["run_spec_sha256"]:
            raise RuntimeError("research run content does not match run_spec_sha256")
        cursor.execute(
            """
            UPDATE research_simulation_runs
            SET status = 'running', claimed_by_worker_id = %s, started_at = now()
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, run_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError(f"queued research run {run_id} could not be claimed")
    connection.commit()
    return ClaimedResearchRun(
        run_spec_sha256=str(row["run_spec_sha256"]),
        execution=execution,
    )


def append_research_round_events(
    connection: Connection[dict[str, object]],
    run_id: UUID,
    worker_id: str,
    round_number: int,
    events: Sequence[SemanticEvent],
) -> None:
    if any(event.round != round_number for event in events):
        raise RuntimeError("research event round does not match the append boundary")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schema_version, run_spec_sha256 FROM research_simulation_runs "
            "WHERE id = %s AND status = 'running' "
            "AND claimed_by_worker_id = %s FOR UPDATE",
            (run_id, worker_id),
        )
        run = cursor.fetchone()
        if run is None:
            connection.rollback()
            raise RuntimeError(f"research run {run_id} is no longer running")
        cursor.execute(
            "SELECT coalesce(max(sequence), 0) AS last_sequence FROM research_run_events "
            "WHERE run_id = %s",
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("cannot read research run event sequence")
        first = int(row["last_sequence"]) + 1
        cursor.executemany(
            """
            INSERT INTO research_run_events (
                run_id, sequence, round, phase, actor_kind, persona_id, agent_position,
                action_type, content, post_id, comment_id, target_post_id,
                observed_at_raw, recorded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            """,
            [
                (
                    run_id,
                    first + offset,
                    event.round,
                    event.phase,
                    event.actor_kind,
                    event.persona_id,
                    event.agent_position,
                    event.action_type,
                    event.content,
                    event.post_id,
                    event.comment_id,
                    event.target_post_id,
                    event.observed_at_raw,
                )
                for offset, event in enumerate(events)
            ],
        )
        if run["schema_version"] == "sandowl-research-simulation-run/v4":
            cursor.execute(
                "SELECT round, memory, memory_sha256 FROM research_run_graph_memory "
                "WHERE run_id = %s ORDER BY round DESC LIMIT 1",
                (run_id,),
            )
            previous_row = cursor.fetchone()
            previous_memory = None
            previous_sha256 = None
            if previous_row is not None:
                if int(previous_row["round"]) != round_number - 1:
                    raise RuntimeError("research graph memory predecessor is not contiguous")
                previous_memory = ResearchRunGraphMemoryState.model_validate_json(
                    json.dumps(previous_row["memory"], ensure_ascii=False, allow_nan=False),
                    strict=True,
                )
                previous_sha256 = str(previous_row["memory_sha256"])
                if graph_memory_sha256(previous_memory) != previous_sha256:
                    raise RuntimeError("research graph memory predecessor hash mismatch")
            memory = build_graph_memory(
                str(run["run_spec_sha256"]),
                round_number,
                first,
                events,
                previous_memory,
                previous_sha256,
            )
            memory_sha256 = graph_memory_sha256(memory)
            cursor.execute(
                "INSERT INTO research_run_graph_memory "
                "(run_id, round, previous_sha256, memory, memory_sha256, created_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, now())",
                (
                    run_id,
                    round_number,
                    previous_sha256,
                    json.dumps(memory.model_dump(mode="json"), ensure_ascii=False, allow_nan=False),
                    memory_sha256,
                ),
            )
    connection.commit()


def complete_research_run(
    connection: Connection[dict[str, object]],
    run_id: UUID,
    worker_id: str,
    result: SemanticSuccess,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT run_spec_sha256 FROM research_simulation_runs WHERE id = %s "
            "AND status = 'running' AND claimed_by_worker_id = %s FOR UPDATE",
            (run_id, worker_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"research run {run_id} is no longer running")
        report_sha = research_run_report_sha256(str(row["run_spec_sha256"]), result.artifact_sha256)
        cursor.execute(
            """
            UPDATE research_simulation_runs SET
                status = 'succeeded', completed_at = now(), artifact_sha256 = %s,
                artifact_size_bytes = %s, user_count = %s, initial_post_count = %s,
                generated_post_count = %s, comment_count = %s, reaction_count = %s,
                do_nothing_count = %s, observed_action_count = %s, rounds_completed = %s,
                limitations = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (
                result.artifact_sha256,
                result.artifact_size_bytes,
                result.user_count,
                result.initial_post_count,
                result.generated_post_count,
                result.comment_count,
                result.reaction_count,
                result.do_nothing_count,
                result.observed_action_count,
                result.rounds_completed,
                list(result.limitations),
                run_id,
                worker_id,
            ),
        )
        cursor.execute(
            "INSERT INTO research_run_reports (id, run_id, report_sha256, created_at) "
            "VALUES (%s, %s, %s, now())",
            (uuid4(), run_id, report_sha),
        )
    connection.commit()


def fail_research_run(
    connection: Connection[dict[str, object]],
    run_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_simulation_runs SET status = 'failed', completed_at = now(), "
            "error_code = %s, error_message = %s WHERE id = %s AND status = 'running' "
            "AND claimed_by_worker_id = %s",
            (failure.code, failure.message, run_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"research run {run_id} is no longer running")
    connection.commit()


def fail_research_runs_owned_by_worker(
    connection: Connection[dict[str, object]], worker_id: str
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_simulation_runs SET status = 'failed', completed_at = now(), "
            "error_code = 'worker_process_restarted', "
            "error_message = 'The owning OASIS worker restarted before completing this run.' "
            "WHERE status = 'running' AND claimed_by_worker_id = %s",
            (worker_id,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated


def fail_orphaned_research_runs(connection: Connection[dict[str, object]], cutoff: datetime) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE research_simulation_runs AS run
            SET status = 'failed', completed_at = now(), error_code = 'worker_heartbeat_lost',
                error_message = 'The OASIS worker stopped before completing this run.'
            WHERE run.status = 'running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats AS heartbeat
                WHERE heartbeat.worker_id = run.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated
