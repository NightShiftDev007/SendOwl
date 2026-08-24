"""Add native multi-source reader reports without mutating v1 archives.

Revision ID: 20260818_core_0054
Revises: 20260818_core_0053
"""

# ruff: noqa: E501

from collections.abc import Sequence

from alembic import op

revision: str = "20260818_core_0054"
down_revision: str | None = "20260818_core_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_SCHEMA = "bounded-report-agent-evidence/v1"
RESEARCH_V1_SCHEMA = "sandowl-research-run-report-agent/v1"
RESEARCH_V2_SCHEMA = "sandowl-research-run-report-agent/v2"
V2_TOOLS = (
    "'read_world_snapshot','read_world_graph','read_simulation_run','read_persona_interviews'"
)
ALL_EVIDENCE_TOOLS = f"'read_media','read_policy',{V2_TOOLS}"


def _install_run_validator(allow_v2: bool) -> None:
    v2_branch = (
        f"""
            ELSIF NEW.schema_version='{RESEARCH_V2_SCHEMA}' THEN
                SELECT report.report_sha256, project.world_model_id,
                       project.world_snapshot_id, project.snapshot_sha256
                INTO linked_report_sha, linked_world_model_id,
                     linked_snapshot_id, linked_snapshot_sha
                FROM research_simulation_runs run
                JOIN research_projects project ON project.id=run.research_project_id
                JOIN research_run_reports report ON report.run_id=run.id
                WHERE run.id=NEW.research_simulation_run_id AND run.status='succeeded'
                FOR SHARE OF run, project, report;
                IF NOT FOUND
                   OR linked_report_sha IS DISTINCT FROM NEW.research_run_report_sha256
                   OR linked_world_model_id IS DISTINCT FROM NEW.world_model_id
                   OR linked_snapshot_id IS DISTINCT FROM NEW.world_snapshot_id
                   OR linked_snapshot_sha IS DISTINCT FROM NEW.snapshot_sha256
                   OR NEW.max_tool_calls NOT BETWEEN 2 AND 4 THEN
                    RAISE EXCEPTION 'ReportAgent v2 research-run scope mismatch'
                        USING ERRCODE='55000';
                END IF;
                expected := report_agent_digest(ARRAY[
                    NEW.schema_version,
                    NEW.world_model_id::text,
                    NEW.world_snapshot_id::text,
                    NEW.snapshot_sha256,
                    NEW.research_simulation_run_id::text,
                    NEW.research_run_report_sha256,
                    NEW.objective,
                    NEW.outline_json,
                    NEW.max_tool_calls::text
                ]);
        """
        if allow_v2
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION validate_report_agent_run_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE snapshot world_snapshots%ROWTYPE;
        DECLARE linked_report_sha text;
        DECLARE linked_world_model_id uuid;
        DECLARE linked_snapshot_id uuid;
        DECLARE linked_snapshot_sha text;
        DECLARE expected text;
        BEGIN
            SELECT * INTO snapshot FROM world_snapshots
            WHERE id=NEW.world_snapshot_id AND sealed_at IS NOT NULL FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'ReportAgent run requires a sealed WorldSnapshot'
                    USING ERRCODE='55000';
            END IF;
            IF snapshot.world_model_id IS DISTINCT FROM NEW.world_model_id
               OR snapshot.snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256 THEN
                RAISE EXCEPTION 'ReportAgent run snapshot scope mismatch'
                    USING ERRCODE='55000';
            END IF;
            IF NEW.schema_version='{LEGACY_SCHEMA}' THEN
                IF NEW.research_simulation_run_id IS NOT NULL
                   OR NEW.research_run_report_sha256 IS NOT NULL THEN
                    RAISE EXCEPTION 'legacy ReportAgent scope cannot bind a research run'
                        USING ERRCODE='55000';
                END IF;
                expected := report_agent_digest(ARRAY[
                    NEW.schema_version, NEW.world_model_id::text,
                    NEW.world_snapshot_id::text, NEW.snapshot_sha256,
                    NEW.objective, NEW.outline_json, NEW.max_tool_calls::text
                ]);
            ELSIF NEW.schema_version='{RESEARCH_V1_SCHEMA}' THEN
                SELECT report.report_sha256, project.world_model_id,
                       project.world_snapshot_id, project.snapshot_sha256
                INTO linked_report_sha, linked_world_model_id,
                     linked_snapshot_id, linked_snapshot_sha
                FROM research_simulation_runs run
                JOIN research_projects project ON project.id=run.research_project_id
                JOIN research_run_reports report ON report.run_id=run.id
                WHERE run.id=NEW.research_simulation_run_id AND run.status='succeeded'
                FOR SHARE OF run, project, report;
                IF NOT FOUND
                   OR linked_report_sha IS DISTINCT FROM NEW.research_run_report_sha256
                   OR linked_world_model_id IS DISTINCT FROM NEW.world_model_id
                   OR linked_snapshot_id IS DISTINCT FROM NEW.world_snapshot_id
                   OR linked_snapshot_sha IS DISTINCT FROM NEW.snapshot_sha256
                   OR NEW.max_tool_calls <> 1 THEN
                    RAISE EXCEPTION 'ReportAgent research-run scope mismatch'
                        USING ERRCODE='55000';
                END IF;
                expected := report_agent_digest(ARRAY[
                    NEW.schema_version, NEW.world_model_id::text,
                    NEW.world_snapshot_id::text, NEW.snapshot_sha256,
                    NEW.research_simulation_run_id::text,
                    NEW.research_run_report_sha256, NEW.objective,
                    NEW.outline_json, NEW.max_tool_calls::text
                ]);
            {v2_branch}
            ELSE
                RAISE EXCEPTION 'unsupported ReportAgent run schema'
                    USING ERRCODE='55000';
            END IF;
            IF NEW.run_sha256 IS DISTINCT FROM expected THEN
                RAISE EXCEPTION 'ReportAgent run hash mismatch' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )


def _install_tool_validator(allow_v2: bool) -> None:
    v2_branch = (
        f"""
            ELSIF parent.schema_version='{RESEARCH_V2_SCHEMA}'
               AND NEW.tool_name IN ({V2_TOOLS})
               AND NEW.result_text IS NOT NULL THEN
                IF NEW.tool_name='read_world_snapshot'
                   AND NEW.target_id IS DISTINCT FROM parent.world_snapshot_id THEN
                    RAISE EXCEPTION 'ReportAgent snapshot source target mismatch'
                        USING ERRCODE='55000';
                ELSIF NEW.tool_name='read_world_graph' THEN
                    SELECT project.world_graph_id INTO linked_graph_id
                    FROM research_simulation_runs run
                    JOIN research_projects project ON project.id=run.research_project_id
                    WHERE run.id=parent.research_simulation_run_id FOR SHARE OF run, project;
                    IF linked_graph_id IS NULL OR NEW.target_id IS DISTINCT FROM linked_graph_id THEN
                        RAISE EXCEPTION 'ReportAgent graph source target mismatch'
                            USING ERRCODE='55000';
                    END IF;
                ELSIF NEW.tool_name IN ('read_simulation_run','read_persona_interviews')
                   AND NEW.target_id IS DISTINCT FROM parent.research_simulation_run_id THEN
                    RAISE EXCEPTION 'ReportAgent run source target mismatch'
                        USING ERRCODE='55000';
                END IF;
                expected_result := encode(
                    digest(convert_to(NEW.result_text, 'UTF8'), 'sha256'), 'hex'
                );
        """
        if allow_v2
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION validate_report_agent_tool_call_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent report_agent_evidence_runs%ROWTYPE;
        DECLARE stored_count integer;
        DECLARE linked_graph_id uuid;
        DECLARE expected_result text;
        DECLARE expected_input text;
        DECLARE expected_call text;
        BEGIN
            SELECT * INTO parent FROM report_agent_evidence_runs
            WHERE id=NEW.run_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'ReportAgent tool call parent run is missing'
                    USING ERRCODE='55000';
            END IF;
            SELECT count(*) INTO stored_count FROM report_agent_evidence_tool_calls
            WHERE run_id=NEW.run_id;
            IF NEW.position <> stored_count OR stored_count >= parent.max_tool_calls THEN
                RAISE EXCEPTION 'ReportAgent tool calls must be contiguous and within budget'
                    USING ERRCODE='55000';
            END IF;
            IF NEW.tool_name='list_evidence' THEN
                expected_result := parent.snapshot_sha256;
            ELSIF NEW.tool_name='read_media' THEN
                SELECT captured_text_sha256 INTO expected_result
                FROM world_snapshot_evidence
                WHERE snapshot_id=parent.world_snapshot_id AND article_id=NEW.target_id;
            ELSIF NEW.tool_name='read_policy' THEN
                SELECT content_sha256 INTO expected_result
                FROM world_snapshot_policy_evidence
                WHERE snapshot_id=parent.world_snapshot_id AND policy_version_id=NEW.target_id;
            ELSIF NEW.tool_name='read_simulation_run'
               AND parent.schema_version='{RESEARCH_V1_SCHEMA}'
               AND NEW.target_id=parent.research_simulation_run_id
               AND NEW.result_text IS NOT NULL THEN
                expected_result := encode(
                    digest(convert_to(NEW.result_text, 'UTF8'), 'sha256'), 'hex'
                );
            {v2_branch}
            ELSE
                RAISE EXCEPTION 'ReportAgent tool is outside its parent scope'
                    USING ERRCODE='55000';
            END IF;
            IF expected_result IS NULL OR NEW.result_sha256 IS DISTINCT FROM expected_result THEN
                RAISE EXCEPTION 'ReportAgent tool result is outside its sealed scope'
                    USING ERRCODE='55000';
            END IF;
            expected_input := report_agent_digest(ARRAY[
                'bounded-report-agent-tool-input/v1', parent.run_sha256,
                NEW.position::text, NEW.tool_name, coalesce(NEW.target_id::text, '')
            ]);
            expected_call := report_agent_digest(ARRAY[
                'bounded-report-agent-tool-call/v1', expected_input, NEW.result_sha256
            ]);
            IF NEW.input_sha256 IS DISTINCT FROM expected_input
               OR NEW.call_sha256 IS DISTINCT FROM expected_call THEN
                RAISE EXCEPTION 'ReportAgent tool call hash mismatch' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )


def _install_draft_functions(evidence_tools: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION report_agent_evidence_calls_sha(target_run_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE STRICT AS $$
        DECLARE call_hashes text[];
        BEGIN
            SELECT array_agg(call_sha256 ORDER BY position) INTO call_hashes
            FROM report_agent_evidence_tool_calls
            WHERE run_id=target_run_id AND tool_name IN ({evidence_tools});
            IF call_hashes IS NULL OR array_length(call_hashes, 1) < 1 THEN
                RAISE EXCEPTION 'ReportAgent cited draft requires audited evidence reads'
                    USING ERRCODE='55000';
            END IF;
            RETURN report_agent_digest(
                array_prepend('bounded-report-agent-evidence-calls/v1', call_hashes)
            );
        END; $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION validate_report_agent_draft_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent report_agent_evidence_runs%ROWTYPE;
        DECLARE expected_calls text;
        DECLARE expected_call_count integer;
        DECLARE expected_input text;
        DECLARE expected_draft text;
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'ReportAgent cited drafts are immutable'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='INSERT' THEN
                SELECT * INTO parent FROM report_agent_evidence_runs
                WHERE id=NEW.run_id FOR SHARE;
                IF NOT FOUND OR parent.run_sha256 IS DISTINCT FROM NEW.run_sha256 THEN
                    RAISE EXCEPTION 'ReportAgent cited draft run scope mismatch'
                        USING ERRCODE='55000';
                END IF;
                expected_calls := report_agent_evidence_calls_sha(NEW.run_id);
                SELECT count(*) INTO expected_call_count
                FROM report_agent_evidence_tool_calls
                WHERE run_id=NEW.run_id AND tool_name IN ({evidence_tools});
                expected_input := report_agent_digest(ARRAY[
                    'bounded-report-agent-cited-draft-input/v1', NEW.run_sha256,
                    expected_calls, NEW.model_name, NEW.semantic_config_sha256,
                    NEW.prompt_schema_version
                ]);
                IF NEW.evidence_call_count IS DISTINCT FROM expected_call_count
                   OR NEW.evidence_calls_sha256 IS DISTINCT FROM expected_calls
                   OR NEW.input_sha256 IS DISTINCT FROM expected_input THEN
                    RAISE EXCEPTION 'ReportAgent cited draft input hash mismatch'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND (to_jsonb(NEW) - ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD) - ARRAY['status','started_at','claimed_by_worker_id']) THEN
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status IN ('succeeded','failed')
               AND (to_jsonb(NEW) - ARRAY['status','completed_at','title','sections_json','draft_sha256','error_code','error_message']) =
                   (to_jsonb(OLD) - ARRAY['status','completed_at','title','sections_json','draft_sha256','error_code','error_message']) THEN
                IF NEW.status='succeeded' THEN
                    expected_draft := report_agent_digest(ARRAY[
                        'bounded-report-agent-cited-draft/v1', NEW.input_sha256,
                        NEW.title, NEW.sections_json
                    ]);
                    IF NEW.draft_sha256 IS DISTINCT FROM expected_draft THEN
                        RAISE EXCEPTION 'ReportAgent cited draft output hash mismatch'
                            USING ERRCODE='55000';
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid ReportAgent cited draft state transition'
                USING ERRCODE='55000';
        END; $$
        """
    )


def _install_interaction_validator(allow_v2: bool) -> None:
    accepted_schemas = (
        f"'{RESEARCH_V1_SCHEMA}','{RESEARCH_V2_SCHEMA}'" if allow_v2 else f"'{RESEARCH_V1_SCHEMA}'"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION validate_agent_interaction_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE native_run report_agent_evidence_runs%ROWTYPE;
        DECLARE draft report_agent_cited_drafts%ROWTYPE;
        DECLARE simulation_project_id uuid;
        DECLARE frozen_source_sha text;
        DECLARE parent agent_interactions%ROWTYPE;
        DECLARE expected_schema text;
        DECLARE expected_input text;
        DECLARE expected_answer text;
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Agent Interactions are immutable' USING ERRCODE='55000';
            END IF;
            IF TG_OP='INSERT' THEN
                SELECT * INTO native_run FROM report_agent_evidence_runs
                WHERE id=NEW.report_agent_run_id
                  AND schema_version IN ({accepted_schemas})
                  AND research_simulation_run_id=NEW.research_simulation_run_id
                FOR SHARE;
                SELECT * INTO draft FROM report_agent_cited_drafts
                WHERE id=NEW.report_agent_draft_id AND run_id=NEW.report_agent_run_id
                  AND status='succeeded' FOR SHARE;
                SELECT research_project_id INTO simulation_project_id
                FROM research_simulation_runs WHERE id=NEW.research_simulation_run_id FOR SHARE;
                SELECT result_sha256 INTO frozen_source_sha
                FROM report_agent_evidence_tool_calls
                WHERE run_id=NEW.report_agent_run_id AND tool_name='read_simulation_run'
                  AND target_id=NEW.research_simulation_run_id FOR SHARE;
                IF native_run.id IS NULL OR draft.id IS NULL
                   OR draft.draft_sha256 IS NULL
                   OR simulation_project_id IS DISTINCT FROM NEW.research_project_id
                   OR native_run.run_sha256 IS DISTINCT FROM NEW.report_agent_run_sha256
                   OR draft.draft_sha256 IS DISTINCT FROM NEW.report_agent_draft_sha256
                   OR frozen_source_sha IS DISTINCT FROM NEW.source_sha256
                   OR draft.model_name IS DISTINCT FROM NEW.model_name
                   OR draft.semantic_config_sha256 IS DISTINCT FROM NEW.semantic_config_sha256 THEN
                    RAISE EXCEPTION 'Agent Interaction single-run scope mismatch' USING ERRCODE='55000';
                END IF;
                IF NEW.parent_interaction_id IS NULL THEN
                    IF NEW.parent_interaction_sha256 IS NOT NULL
                       OR NEW.parent_answer_sha256 IS NOT NULL
                       OR NEW.conversation_depth <> 0 THEN
                        RAISE EXCEPTION 'Agent Interaction root lineage mismatch' USING ERRCODE='55000';
                    END IF;
                    expected_schema := 'sandowl-agent-interaction/v1';
                ELSE
                    SELECT * INTO parent FROM agent_interactions
                    WHERE id=NEW.parent_interaction_id AND status='succeeded' FOR SHARE;
                    IF parent.id IS NULL
                       OR parent.report_agent_draft_id IS DISTINCT FROM NEW.report_agent_draft_id
                       OR parent.interaction_sha256 IS DISTINCT FROM NEW.parent_interaction_sha256
                       OR parent.answer_sha256 IS DISTINCT FROM NEW.parent_answer_sha256
                       OR NEW.conversation_depth <> parent.conversation_depth + 1 THEN
                        RAISE EXCEPTION 'Agent Interaction follow-up lineage mismatch' USING ERRCODE='55000';
                    END IF;
                    expected_schema := 'sandowl-agent-interaction/v2';
                END IF;
                expected_input := report_agent_digest(ARRAY[
                    expected_schema, NEW.research_project_id::text,
                    NEW.research_simulation_run_id::text, NEW.report_agent_run_sha256,
                    NEW.report_agent_draft_sha256, NEW.source_sha256, NEW.question,
                    coalesce(NEW.parent_interaction_sha256, ''),
                    coalesce(NEW.parent_answer_sha256, '')
                ]);
                IF NEW.prompt_schema_version IS DISTINCT FROM expected_schema
                   OR NEW.interaction_sha256 IS DISTINCT FROM expected_input
                   OR NEW.status <> 'queued' OR NEW.started_at IS NOT NULL
                   OR NEW.completed_at IS NOT NULL OR NEW.claimed_by_worker_id IS NOT NULL
                   OR NEW.answer_markdown IS NOT NULL OR NEW.citations_json IS NOT NULL
                   OR NEW.answer_sha256 IS NOT NULL OR NEW.error_code IS NOT NULL
                   OR NEW.error_message IS NOT NULL THEN
                    RAISE EXCEPTION 'Agent Interaction queued input mismatch' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND NEW.started_at IS NOT NULL AND NEW.claimed_by_worker_id IS NOT NULL
               AND (to_jsonb(NEW) - ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD) - ARRAY['status','started_at','claimed_by_worker_id']) THEN
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status IN ('succeeded','failed')
               AND NEW.completed_at IS NOT NULL
               AND (to_jsonb(NEW) - ARRAY['status','completed_at','answer_markdown','citations_json','answer_sha256','error_code','error_message']) =
                   (to_jsonb(OLD) - ARRAY['status','completed_at','answer_markdown','citations_json','answer_sha256','error_code','error_message']) THEN
                IF NEW.status='succeeded' THEN
                    expected_answer := report_agent_digest(ARRAY[
                        'sandowl-agent-interaction-answer/v1', NEW.interaction_sha256,
                        NEW.answer_markdown, NEW.citations_json
                    ]);
                    IF NEW.answer_markdown IS NULL OR NEW.citations_json IS NULL
                       OR NEW.answer_sha256 IS DISTINCT FROM expected_answer
                       OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL THEN
                        RAISE EXCEPTION 'Agent Interaction answer mismatch' USING ERRCODE='55000';
                    END IF;
                ELSIF NEW.answer_markdown IS NOT NULL OR NEW.citations_json IS NOT NULL
                   OR NEW.answer_sha256 IS NOT NULL OR NEW.error_code IS NULL
                   OR NEW.error_message IS NULL THEN
                    RAISE EXCEPTION 'Agent Interaction failure mismatch' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid Agent Interaction state transition' USING ERRCODE='55000';
        END; $$
        """
    )


def upgrade() -> None:
    op.drop_constraint(
        "uq_report_agent_runs_research_run", "report_agent_evidence_runs", type_="unique"
    )
    op.create_unique_constraint(
        "uq_report_agent_runs_research_run_schema",
        "report_agent_evidence_runs",
        ["research_simulation_run_id", "schema_version"],
    )
    op.drop_constraint("ck_report_agent_run_schema", "report_agent_evidence_runs", type_="check")
    op.create_check_constraint(
        "ck_report_agent_run_schema",
        "report_agent_evidence_runs",
        f"(schema_version='{LEGACY_SCHEMA}' AND research_simulation_run_id IS NULL AND research_run_report_sha256 IS NULL) OR "
        f"(schema_version='{RESEARCH_V1_SCHEMA}' AND research_simulation_run_id IS NOT NULL AND research_run_report_sha256 ~ '^[a-f0-9]{{64}}$' AND max_tool_calls=1) OR "
        f"(schema_version='{RESEARCH_V2_SCHEMA}' AND research_simulation_run_id IS NOT NULL AND research_run_report_sha256 ~ '^[a-f0-9]{{64}}$' AND max_tool_calls BETWEEN 2 AND 4)",
    )
    op.drop_constraint(
        "ck_report_agent_tool_call_target", "report_agent_evidence_tool_calls", type_="check"
    )
    op.drop_constraint(
        "ck_report_agent_tool_call_name", "report_agent_evidence_tool_calls", type_="check"
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_name",
        "report_agent_evidence_tool_calls",
        f"tool_name IN ('list_evidence','read_media','read_policy',{V2_TOOLS})",
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_target",
        "report_agent_evidence_tool_calls",
        "(tool_name='list_evidence' AND target_id IS NULL AND result_text IS NULL) OR "
        "(tool_name IN ('read_media','read_policy') AND target_id IS NOT NULL AND result_text IS NULL) OR "
        f"(tool_name IN ({V2_TOOLS}) AND target_id IS NOT NULL AND length(result_text) BETWEEN 1 AND 80000)",
    )
    _install_run_validator(True)
    _install_tool_validator(True)
    _install_draft_functions(ALL_EVIDENCE_TOOLS)
    _install_interaction_validator(True)


def downgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM report_agent_evidence_runs
                WHERE schema_version='{RESEARCH_V2_SCHEMA}'
            ) THEN
                RAISE EXCEPTION 'cannot downgrade while ReportAgent v2 scopes exist';
            END IF;
        END $$
        """
    )
    _install_run_validator(False)
    _install_tool_validator(False)
    _install_draft_functions("'read_media','read_policy','read_simulation_run'")
    _install_interaction_validator(False)
    op.drop_constraint(
        "ck_report_agent_tool_call_target", "report_agent_evidence_tool_calls", type_="check"
    )
    op.drop_constraint(
        "ck_report_agent_tool_call_name", "report_agent_evidence_tool_calls", type_="check"
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_name",
        "report_agent_evidence_tool_calls",
        "tool_name IN ('list_evidence','read_media','read_policy','read_simulation_run')",
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_target",
        "report_agent_evidence_tool_calls",
        "(tool_name='list_evidence' AND target_id IS NULL AND result_text IS NULL) OR "
        "(tool_name IN ('read_media','read_policy') AND target_id IS NOT NULL AND result_text IS NULL) OR "
        "(tool_name='read_simulation_run' AND target_id IS NOT NULL AND length(result_text) BETWEEN 1 AND 500000)",
    )
    op.drop_constraint("ck_report_agent_run_schema", "report_agent_evidence_runs", type_="check")
    op.create_check_constraint(
        "ck_report_agent_run_schema",
        "report_agent_evidence_runs",
        f"(schema_version='{LEGACY_SCHEMA}' AND research_simulation_run_id IS NULL AND research_run_report_sha256 IS NULL) OR "
        f"(schema_version='{RESEARCH_V1_SCHEMA}' AND research_simulation_run_id IS NOT NULL AND research_run_report_sha256 ~ '^[a-f0-9]{{64}}$' AND max_tool_calls=1)",
    )
    op.drop_constraint(
        "uq_report_agent_runs_research_run_schema",
        "report_agent_evidence_runs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_report_agent_runs_research_run",
        "report_agent_evidence_runs",
        ["research_simulation_run_id"],
    )
