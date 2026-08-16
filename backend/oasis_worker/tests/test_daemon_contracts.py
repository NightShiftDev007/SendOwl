import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from oasis_worker.contracts import (
    ArtifactResult,
    JobResult,
    ObservedPost,
    ObservedState,
    ObservedUser,
    SignupTrace,
    SignupTraceInfo,
)
from oasis_worker.daemon import load_daemon_settings, normalize_job_result
from oasis_worker.errors import OasisWorkerError
from oasis_worker.queue_contracts import ClaimedRun, QueuePost

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-4222-8222-222222222222")


def _claimed() -> ClaimedRun:
    scenario_id = UUID("33333333-3333-4333-8333-333333333333")
    variant_id = UUID("44444444-4444-4444-8444-444444444444")
    digest = "ce69d490dd076e6f"
    return ClaimedRun(
        id=RUN_ID,
        status="running",
        mode="reddit_manual_smoke",
        scenario_id=scenario_id,
        scenario_sha256="a" * 64,
        variant_id=variant_id,
        variant_name="Clarify",
        world_snapshot_id=SNAPSHOT_ID,
        snapshot_sha256="b" * 64,
        seed=7,
        actor_user_name=f"scenario_{digest}",
        actor_name=f"Scenario actor {digest}",
        actor_bio=(
            f"Synthetic actor compiled from Scenario {scenario_id} variant {variant_id}. "
            "Manual OASIS platform smoke only."
        ),
        input_sha256="c" * 64,
        posts=(QueuePost(position=0, content="Verified post.", offset_minutes=0),),
    )


def _job_result(artifact: Path, reported_path: Path) -> JobResult:
    run = _claimed()
    content = artifact.read_bytes()
    created_at = "2026-08-12 00:00:00"
    return JobResult(
        schema_version="oasis-manual-smoke/v2",
        run_id=str(run.id),
        seed=run.seed,
        engine="camel-oasis",
        engine_version="0.2.5",
        camel_version="0.2.78",
        mode="reddit_manual_smoke",
        artifact=ArtifactResult(
            database_path=str(reported_path),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        ),
        observed=ObservedState(
            user=ObservedUser(
                user_id=0,
                agent_id=0,
                user_name=run.actor_user_name,
                name=run.actor_name,
                bio=run.actor_bio,
                created_at=created_at,
            ),
            posts=(
                ObservedPost(
                    post_id=1,
                    user_id=0,
                    content="Verified post.",
                    created_at=created_at,
                ),
            ),
            traces=(
                SignupTrace(
                    position=0,
                    user_id=0,
                    created_at=created_at,
                    action="sign_up",
                    info=SignupTraceInfo(
                        name=run.actor_name,
                        user_name=run.actor_user_name,
                        bio=run.actor_bio,
                    ),
                ),
                # The exact trace subtype is exercised by the real integration test.
            ),
        ),
        limitations=("Manual smoke only.",),
    )


def test_daemon_settings_require_explicit_environment_and_normalize_async_url() -> None:
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql+asyncpg://app:secret@postgres:5432/decision",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "compose-oasis-worker",
        }
    )

    assert settings.database_url == "postgresql://app:secret@postgres:5432/decision"
    assert settings.artifact_root == Path("/artifacts")
    assert settings.worker_id == "compose-oasis-worker"
    assert settings.semantic_config is None
    assert settings.survey_config is None
    assert settings.chat_config is None


def test_daemon_settings_enable_semantic_runtime_only_with_complete_configuration() -> None:
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "worker",
            "LLM_API_KEY": "secret-key",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL_NAME": "provider-model",
        }
    )

    assert settings.semantic_config is not None
    assert settings.semantic_config.model_name == "provider-model"
    assert settings.semantic_config.prompt_schema_version == "matraix-semantic-profile/v1"
    assert settings.survey_config is not None
    assert settings.survey_config.model_name == "provider-model"
    assert settings.survey_config.prompt_schema_version == ("matraix-survey-scenario-preference/v1")
    assert settings.survey_config.config_sha256 != settings.semantic_config.config_sha256
    assert settings.chat_config is None
    assert "secret-key" not in repr(settings)


def test_daemon_settings_enable_chat_only_with_explicit_sut_endpoint() -> None:
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "worker",
            "LLM_API_KEY": "secret-key",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL_NAME": "provider-model",
            "CHATBOT_SUT_BASE_URL": "http://acme-support-sample:8000",
            "CHATBOT_MCP_SUT_URL": "http://acme-support-mcp-sample:8000/mcp",
        }
    )

    assert settings.chat_config is not None
    assert settings.chat_config.model_name == "provider-model"
    assert settings.chat_config.sut_task_id == "sendowl/matraix-acme-rest-mcp-suite"
    assert settings.chat_config.sut_task_version == "1.0.0"
    assert settings.chat_config.sut_spec_sha256 == (
        "0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a"
    )
    assert "secret-key" not in repr(settings)
    assert "acme-support-sample" not in repr(settings)


@pytest.mark.parametrize(
    ("sut_url", "match"),
    [
        ("", "both be configured"),
        ("acme-support-sample:8000", "HTTP\\(S\\) URL"),
        ("http://user:password@acme-support-sample:8000", "must not contain credentials"),
    ],
)
def test_daemon_settings_reject_invalid_chat_sut_endpoint(
    sut_url: str,
    match: str,
) -> None:
    with pytest.raises(OasisWorkerError, match=match):
        load_daemon_settings(
            {
                "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
                "OASIS_ARTIFACT_ROOT": "/artifacts",
                "OASIS_WORKER_ID": "worker",
                "LLM_API_KEY": "secret-key",
                "LLM_BASE_URL": "https://provider.example/v1",
                "LLM_MODEL_NAME": "provider-model",
                "CHATBOT_SUT_BASE_URL": sut_url,
                "CHATBOT_MCP_SUT_URL": "http://acme-support-mcp-sample:8000/mcp",
            }
        )


def test_daemon_settings_keep_chat_disabled_when_compose_sut_has_no_provider() -> None:
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "worker",
            "LLM_API_KEY": "",
            "LLM_BASE_URL": "",
            "LLM_MODEL_NAME": "",
            "CHATBOT_SUT_BASE_URL": "http://acme-support-sample:8000",
            "CHATBOT_MCP_SUT_URL": "http://acme-support-mcp-sample:8000/mcp",
        }
    )

    assert settings.semantic_config is None
    assert settings.survey_config is None
    assert settings.chat_config is None


@pytest.mark.parametrize(
    "partial",
    [
        {"LLM_API_KEY": "secret-key"},
        {
            "LLM_API_KEY": "secret-key",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL_NAME": "",
        },
    ],
)
def test_daemon_settings_reject_partial_semantic_configuration(
    partial: dict[str, str],
) -> None:
    environment = {
        "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
        "OASIS_ARTIFACT_ROOT": "/artifacts",
        "OASIS_WORKER_ID": "worker",
        "CHATBOT_SUT_BASE_URL": "http://acme-support-sample:8000",
        "CHATBOT_MCP_SUT_URL": "http://acme-support-mcp-sample:8000/mcp",
        **partial,
    }

    with pytest.raises(OasisWorkerError, match="semantic LLM configuration requires"):
        load_daemon_settings(environment)


def test_daemon_settings_treat_all_empty_compose_semantic_values_as_disabled() -> None:
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "worker",
            "LLM_API_KEY": "",
            "LLM_BASE_URL": "",
            "LLM_MODEL_NAME": "",
        }
    )

    assert settings.semantic_config is None
    assert settings.survey_config is None
    assert settings.chat_config is None


def test_daemon_settings_reject_missing_values_without_echoing_secrets() -> None:
    with pytest.raises(OasisWorkerError, match="OASIS_ARTIFACT_ROOT is required"):
        load_daemon_settings(
            {
                "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
                "OASIS_WORKER_ID": "worker",
            }
        )


def test_normalize_result_rejects_artifact_path_misbinding(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    expected_directory = artifact_root / str(RUN_ID)
    expected_directory.mkdir(parents=True)
    expected_path = expected_directory / f"{RUN_ID}.sqlite3"
    expected_path.write_bytes(b"verified artifact")
    wrong_path = tmp_path / "wrong.sqlite3"

    with pytest.raises(OasisWorkerError, match="artifact path mismatch"):
        normalize_job_result(
            _claimed(),
            artifact_root,
            _job_result(expected_path, wrong_path),
        )


def test_semantic_queue_is_claimed_only_by_the_matching_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from semantic_fixtures import CONFIG_SHA256, build_trial

    from oasis_worker import daemon
    from oasis_worker.daemon import DaemonSettings
    from oasis_worker.semantic_contracts import SemanticRuntimeConfig

    trial = build_trial(persona_count=1, selected_position=0)
    compatible = SemanticRuntimeConfig(
        api_key="compatible-secret",
        base_url="https://provider.example/v1",
        model_name=trial.experiment.model_name,
        config_sha256=CONFIG_SHA256,
        prompt_schema_version=trial.experiment.prompt_schema_version,
    )
    incompatible = compatible.model_copy(update={"config_sha256": "f" * 64})
    claimed_configs: list[str] = []

    class RecordingConnection:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

    def semantic_head(
        _connection: object,
        runtime_config: SemanticRuntimeConfig,
    ) -> tuple[UUID, datetime] | None:
        if runtime_config != compatible:
            return None
        return trial.id, trial.created_at

    def claim_semantic(
        _connection: object,
        _trial_id: UUID,
        _worker_id: str,
        runtime_config: SemanticRuntimeConfig,
    ):
        claimed_configs.append(runtime_config.config_sha256)
        return trial

    monkeypatch.setattr(daemon, "platform_smoke_queue_head", lambda _connection: None)
    monkeypatch.setattr(daemon, "semantic_queue_head", semantic_head)
    monkeypatch.setattr(daemon, "world_graph_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "report_question_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "persona_interview_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "survey_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "chat_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "web_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "linux_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "claim_semantic_trial", claim_semantic)
    connection = RecordingConnection()

    incompatible_result = daemon._claim_next_job(  # type: ignore[arg-type]
        DaemonSettings(
            database_url="postgresql://unused:unused@localhost/unused",
            artifact_root=Path("/artifacts"),
            worker_id="incompatible-worker",
            semantic_config=incompatible,
            survey_config=None,
            chat_config=None,
            web_config=None,
            linux_config=None,
        ),
        connection,
    )
    compatible_result = daemon._claim_next_job(  # type: ignore[arg-type]
        DaemonSettings(
            database_url="postgresql://unused:unused@localhost/unused",
            artifact_root=Path("/artifacts"),
            worker_id="compatible-worker",
            semantic_config=compatible,
            survey_config=None,
            chat_config=None,
            web_config=None,
            linux_config=None,
        ),
        connection,
    )

    assert incompatible_result is None
    assert compatible_result == trial
    assert claimed_configs == [CONFIG_SHA256]


def test_oldest_survey_job_is_fairly_claimed_from_the_shared_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oasis_worker import daemon
    from oasis_worker.daemon import DaemonSettings
    from oasis_worker.semantic_contracts import SemanticRuntimeConfig
    from oasis_worker.survey_contracts import SurveyRuntimeConfig

    semantic_config = SemanticRuntimeConfig(
        api_key="secret",
        base_url="https://provider.example/v1",
        model_name="provider-model",
        config_sha256="a" * 64,
        prompt_schema_version="matraix-semantic-profile/v1",
    )
    survey_config = SurveyRuntimeConfig(
        api_key="secret",
        base_url="https://provider.example/v1",
        model_name="provider-model",
        config_sha256="b" * 64,
        prompt_schema_version="matraix-survey-scenario-preference/v1",
    )
    semantic_id = UUID("81000000-0000-4000-8000-000000000001")
    survey_id = UUID("82000000-0000-4000-8000-000000000001")
    claimed_configs: list[str] = []
    marker = object()

    class RecordingConnection:
        def commit(self) -> None:
            raise AssertionError("a queued survey job should be claimed without an empty commit")

    def claim_survey(
        _connection: object,
        claimed_id: UUID,
        _worker_id: str,
        runtime_config: SurveyRuntimeConfig,
    ) -> object:
        assert claimed_id == survey_id
        claimed_configs.append(runtime_config.config_sha256)
        return marker

    monkeypatch.setattr(daemon, "platform_smoke_queue_head", lambda _connection: None)
    monkeypatch.setattr(
        daemon,
        "semantic_queue_head",
        lambda _connection, _config: (semantic_id, datetime(2026, 8, 13, 2, 0)),
    )
    monkeypatch.setattr(daemon, "world_graph_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "report_question_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "persona_interview_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(
        daemon,
        "survey_queue_head",
        lambda _connection, _config: (survey_id, datetime(2026, 8, 13, 1, 0)),
    )
    monkeypatch.setattr(daemon, "chat_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "web_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "linux_queue_head", lambda _connection, _config: None)
    monkeypatch.setattr(daemon, "claim_survey_trial", claim_survey)

    result = daemon._claim_next_job(  # type: ignore[arg-type]
        DaemonSettings(
            database_url="postgresql://unused:unused@localhost/unused",
            artifact_root=Path("/artifacts"),
            worker_id="shared-worker",
            semantic_config=semantic_config,
            survey_config=survey_config,
            chat_config=None,
            web_config=None,
            linux_config=None,
        ),
        RecordingConnection(),
    )

    assert result is marker
    assert claimed_configs == [survey_config.config_sha256]


def test_semantic_failure_is_actionable_bounded_and_redacts_runtime_secrets() -> None:
    from oasis_worker.daemon import _semantic_failure
    from oasis_worker.errors import OasisExecutionError
    from oasis_worker.semantic_contracts import SemanticRuntimeConfig

    class AuthenticationError(Exception):
        pass

    config = SemanticRuntimeConfig(
        api_key="top-secret-key",
        base_url="https://private-provider.example/v1",
        model_name="provider-model",
        config_sha256="a" * 64,
        prompt_schema_version="matraix-semantic-profile/v1",
    )
    cause = AuthenticationError("raw provider response contains top-secret-key")
    error = OasisExecutionError(
        "provider request at https://private-provider.example/v1\nfailed for audience agent 2"
    )
    error.__cause__ = cause

    failure = _semantic_failure(error, config)

    assert failure.code == "provider_auth"
    assert "audience agent 2" in failure.message
    assert "top-secret-key" not in failure.message
    assert "private-provider.example" not in failure.message
    assert "\n" not in failure.message
    assert len(failure.message) <= 500


def test_survey_failure_uses_safe_provider_codes_and_redacts_runtime_secrets() -> None:
    from oasis_worker.daemon import _semantic_failure
    from oasis_worker.errors import OasisExecutionError
    from oasis_worker.survey_contracts import SurveyRuntimeConfig

    class AuthenticationError(Exception):
        pass

    config = SurveyRuntimeConfig(
        api_key="survey-secret-key",
        base_url="https://private-survey-provider.example/v1",
        model_name="provider-model",
        config_sha256="b" * 64,
        prompt_schema_version="matraix-survey-scenario-preference/v1",
    )
    error = OasisExecutionError(
        "survey provider at https://private-survey-provider.example/v1 rejected survey-secret-key"
    )
    error.__cause__ = AuthenticationError("raw provider body")

    failure = _semantic_failure(error, config)

    assert failure.code == "provider_auth"
    assert failure.message.startswith("Survey trial failed:")
    assert "survey-secret-key" not in failure.message
    assert "private-survey-provider.example" not in failure.message
    assert len(failure.message) <= 500


def test_chat_failure_redacts_provider_and_internal_sut_runtime_values() -> None:
    from oasis_worker.chat_contracts import ChatRuntimeConfig
    from oasis_worker.daemon import _semantic_failure
    from oasis_worker.errors import OasisExecutionError

    class AuthenticationError(Exception):
        pass

    config = ChatRuntimeConfig(
        api_key="chat-secret-key",
        provider_base_url="https://private-chat-provider.example/v1",
        rest_sut_base_url="http://acme-support-sample:8000",
        mcp_sut_url="http://acme-support-mcp-sample:8000/mcp",
        model_name="provider-model",
        config_sha256="c" * 64,
        prompt_schema_version="matraix-chat-acme-support/v1",
        sut_task_id="sendowl/matraix-acme-rest-mcp-suite",
        sut_task_version="1.0.0",
        sut_spec_sha256=("0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a"),
    )
    error = OasisExecutionError(
        "chat provider at https://private-chat-provider.example/v1 rejected chat-secret-key "
        "while calling http://acme-support-sample:8000"
    )
    error.__cause__ = AuthenticationError("raw provider response")

    failure = _semantic_failure(error, config)

    assert failure.code == "provider_auth"
    assert failure.message.startswith("Chat trial failed:")
    assert "chat-secret-key" not in failure.message
    assert "private-chat-provider.example" not in failure.message
    assert "acme-support-sample" not in failure.message
    assert len(failure.message) <= 500


def test_heartbeat_chat_fields_match_0021_and_never_persist_runtime_secrets() -> None:
    from oasis_worker.chat_contracts import (
        CHAT_PROMPT_SCHEMA_VERSION,
        CHAT_SUITE_ID,
        CHAT_SUITE_SHA256,
        CHAT_SUITE_VERSION,
        ChatRuntimeConfig,
    )
    from oasis_worker.chat_hashing import chat_config_sha256
    from oasis_worker.queue import update_heartbeat
    from oasis_worker.semantic_contracts import SemanticRuntimeConfig

    executions: list[tuple[str, tuple[object, ...]]] = []

    class RecordingConnection:
        def cursor(self) -> "RecordingConnection":
            return self

        def __enter__(self) -> "RecordingConnection":
            return self

        def __exit__(
            self,
            _exception_type: object,
            _exception: object,
            _traceback: object,
        ) -> None:
            return None

        def execute(self, query: object, parameters: tuple[object, ...]) -> None:
            executions.append((str(query), parameters))

        def commit(self) -> None:
            return None

    semantic = SemanticRuntimeConfig(
        api_key="provider-secret",
        base_url="https://private-provider.example/v1",
        model_name="provider-model",
        config_sha256="a" * 64,
        prompt_schema_version="matraix-semantic-profile/v1",
    )
    chat = ChatRuntimeConfig(
        api_key=semantic.api_key,
        provider_base_url=semantic.base_url,
        rest_sut_base_url="http://acme-support-sample:8000",
        mcp_sut_url="http://acme-support-mcp-sample:8000/mcp",
        model_name=semantic.model_name,
        config_sha256=chat_config_sha256(semantic.base_url, semantic.model_name),
        prompt_schema_version=CHAT_PROMPT_SCHEMA_VERSION,
        sut_task_id=CHAT_SUITE_ID,
        sut_task_version=CHAT_SUITE_VERSION,
        sut_spec_sha256=CHAT_SUITE_SHA256,
    )
    started_at = datetime(2026, 8, 13, tzinfo=UTC)

    update_heartbeat(  # type: ignore[arg-type]
        RecordingConnection(),
        "worker-chat",
        started_at,
        True,
        semantic,
        None,
        chat,
        None,
        None,
    )
    update_heartbeat(  # type: ignore[arg-type]
        RecordingConnection(),
        "worker-no-chat",
        started_at,
        True,
        semantic,
        None,
        None,
        None,
        None,
    )

    configured_query, configured_parameters = executions[0]
    assert configured_query.count("%s") == len(configured_parameters) == 35
    assert configured_parameters[14:21] == (
        True,
        chat.model_name,
        chat.config_sha256,
        CHAT_PROMPT_SCHEMA_VERSION,
        CHAT_SUITE_ID,
        CHAT_SUITE_VERSION,
        CHAT_SUITE_SHA256,
    )
    _, disabled_parameters = executions[1]
    assert disabled_parameters[14:21] == (False, None, None, None, None, None, None)
    assert disabled_parameters[21:27] == (False, None, None, None, None, None)
    assert disabled_parameters[27:33] == (False, None, None, None, None, None)
    rendered = repr(executions)
    assert "provider-secret" not in rendered
    assert "private-provider.example" not in rendered
    assert "acme-support-sample" not in rendered
