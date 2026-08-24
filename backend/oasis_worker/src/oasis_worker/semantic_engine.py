"""Real small-cohort CAMEL-OASIS semantic trial execution and verification."""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from camel.messages import OpenAIMessage
from camel.models import BaseModelBackend, ModelFactory, StubModel
from camel.prompts import TextPrompt
from camel.responses import ChatAgentResponse
from camel.types import ChatCompletion, ChatCompletionChunk, ModelPlatformType, ModelType
from camel.utils import BaseTokenCounter
from oasis import (
    ActionType,
    AgentGraph,
    DefaultPlatformType,
    LLMAction,
    ManualAction,
    SocialAgent,
    UserInfo,
    make,
)
from oasis.social_agent.agent_environment import SocialEnvironment
from openai import AsyncStream, Stream
from openai.lib.streaming.chat import (
    AsyncChatCompletionStreamManager,
    ChatCompletionStreamManager,
)
from pydantic import BaseModel

from oasis_worker.engine import EXPECTED_CAMEL_VERSION, EXPECTED_OASIS_VERSION
from oasis_worker.errors import (
    ArtifactConflictError,
    ArtifactVerificationError,
    OasisExecutionError,
)
from oasis_worker.semantic_contracts import (
    ALLOWED_AUDIENCE_ACTION_NAMES,
    LOW_INFORMATION_VALUES,
    MAX_PROFILE_ATTRIBUTES,
    PROFILE_TEMPLATE_TEXT,
    ClaimedSemanticTrial,
    SemanticEvent,
    SemanticPersona,
    SemanticRuntimeConfig,
    SemanticSuccess,
    SocialSimulationExecution,
)
from oasis_worker.semantic_hashing import (
    MODEL_CONTEXT_TOKEN_LIMIT,
    MODEL_ENABLE_THINKING,
    MODEL_OUTPUT_MAX_TOKENS,
    MODEL_TOOL_CHOICE,
    REPORT_DOMAIN_OUTPUT_MAX_TOKENS,
)

MODEL_TIMEOUT_SECONDS = 90.0
MODEL_MAX_RETRIES = 2
ALLOWED_AUDIENCE_ACTIONS = (*(ActionType(name) for name in ALLOWED_AUDIENCE_ACTION_NAMES),)
SEMANTIC_LIMITATIONS = (
    "OpenAI-compatible provider behavior is nondeterministic; the recorded seed does not "
    "guarantee provider-level reproducibility.",
    "This social simulation is limited to at most eight personas and six rounds on Reddit.",
    "The trial has no real social network; agents only observe OASIS recommendations.",
    "Persona prompts use a deterministic bounded projection of at most forty informative "
    "profile attributes and do not contain hidden analysis instructions.",
    "Events are observed actions only; no stance, reach, prediction, or decision verdict is "
    "inferred.",
)

PROFILE_TEMPLATE = TextPrompt(PROFILE_TEMPLATE_TEXT)

ModelRunResult: TypeAlias = (
    ChatCompletion | Stream[ChatCompletionChunk] | ChatCompletionStreamManager[BaseModel]
)
AsyncModelRunResult: TypeAlias = (
    ChatCompletion | AsyncStream[ChatCompletionChunk] | AsyncChatCompletionStreamManager[BaseModel]
)


@dataclass(frozen=True)
class ProfileProjection:
    text: str
    included_count: int
    eligible_count: int
    total_count: int


@dataclass(frozen=True)
class TraceObservation:
    rowid: int
    event: SemanticEvent


class BoundedSemanticEnvironment(SocialEnvironment):
    """OASIS environment adapter for a trial with no follower network."""

    async def get_followers_env(self) -> str:
        return self.followers_env_template.substitute(num_followers=0)

    async def get_follows_env(self) -> str:
        return self.follows_env_template.substitute(num_follows=0)


class StrictSocialAgent(SocialAgent):
    """Turn OASIS/CAMEL's swallowed provider and tool failures into trial failures."""

    async def perform_action_by_llm(self):  # type: ignore[no-untyped-def]
        response = await super().perform_action_by_llm()
        if isinstance(response, BaseException):
            raise OasisExecutionError(
                "semantic provider call failed for audience agent "
                f"{self.social_agent_id} with {type(response).__name__}"
            ) from response
        if not isinstance(response, ChatAgentResponse):
            raise OasisExecutionError(
                f"audience agent {self.social_agent_id} did not return a ChatAgentResponse; "
                f"observed {type(response).__name__}"
            )
        tool_calls = response.info.get("tool_calls")
        if not isinstance(tool_calls, list) or len(tool_calls) != 1:
            observed = len(tool_calls) if isinstance(tool_calls, list) else 0
            raise OasisExecutionError(
                f"audience agent {self.social_agent_id} must make exactly one tool call; "
                f"observed {observed}"
            )
        result = tool_calls[0].result
        if not isinstance(result, dict) or result.get("success") is not True:
            raise OasisExecutionError(
                f"audience agent {self.social_agent_id} tool call was not successful"
            )
        return response


class SemanticOpenAIBackend(BaseModelBackend):
    """Keep CAMEL context accounting separate from provider output limits."""

    def __init__(self, backend: BaseModelBackend) -> None:
        self._backend = backend
        super().__init__(
            model_type=backend.model_type,
            model_config_dict=backend.model_config_dict,
            api_key=None,
            url=None,
            token_counter=backend.token_counter,
            timeout=None,
            max_retries=MODEL_MAX_RETRIES,
        )

    @property
    def token_counter(self) -> BaseTokenCounter:
        return self._backend.token_counter

    @property
    def token_limit(self) -> int:
        return MODEL_CONTEXT_TOKEN_LIMIT

    def _run(
        self,
        messages: list[OpenAIMessage],
        response_format: type[BaseModel] | None = None,
        tools: list[dict[str, object]] | None = None,
    ) -> ModelRunResult:
        return self._backend.run(messages, response_format, tools)

    async def _arun(
        self,
        messages: list[OpenAIMessage],
        response_format: type[BaseModel] | None = None,
        tools: list[dict[str, object]] | None = None,
    ) -> AsyncModelRunResult:
        return await self._backend.arun(messages, response_format, tools)


async def probe_semantic_runtime(model_backend: BaseModelBackend) -> None:
    """Require one real provider-generated tool call before advertising readiness."""
    messages: list[OpenAIMessage] = [
        {
            "role": "system",
            "content": "Return exactly one call to the supplied do_nothing function.",
        },
        {
            "role": "user",
            "content": "Perform the required readiness action now.",
        },
    ]
    tools: list[dict[str, object]] = [
        {
            "type": "function",
            "function": {
                "name": "do_nothing",
                "description": "Confirm semantic tool-call readiness without side effects.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    try:
        response = await model_backend.arun(messages, None, tools)
    except Exception as error:
        raise OasisExecutionError(
            "semantic provider readiness probe failed with "
            f"{type(error).__name__} after bounded provider retries"
        ) from error
    if not isinstance(response, ChatCompletion) or len(response.choices) != 1:
        raise OasisExecutionError(
            "semantic provider readiness probe did not return one chat completion choice"
        )
    tool_calls = response.choices[0].message.tool_calls
    if tool_calls is None or len(tool_calls) != 1:
        observed = 0 if tool_calls is None else len(tool_calls)
        raise OasisExecutionError(
            f"semantic provider readiness probe requires exactly one tool call; observed {observed}"
        )
    function = tool_calls[0].function
    if function.name != "do_nothing":
        raise OasisExecutionError(
            "semantic provider readiness probe returned an unexpected tool name"
        )
    try:
        arguments: object = json.loads(function.arguments)
    except json.JSONDecodeError as error:
        raise OasisExecutionError(
            "semantic provider readiness probe returned invalid tool arguments"
        ) from error
    if arguments != {}:
        raise OasisExecutionError(
            "semantic provider readiness probe returned unexpected tool arguments"
        )


def _create_provider_model(
    config: SemanticRuntimeConfig,
    output_max_tokens: int,
) -> BaseModelBackend:
    backend = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=config.model_name,
        model_config_dict={
            "max_tokens": output_max_tokens,
            "tool_choice": MODEL_TOOL_CHOICE,
            "extra_body": {"enable_thinking": MODEL_ENABLE_THINKING},
        },
        api_key=config.api_key,
        url=config.base_url,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )
    return SemanticOpenAIBackend(backend)


def create_provider_model(config: SemanticRuntimeConfig) -> BaseModelBackend:
    """Build the bounded semantic-simulation provider backend."""
    return _create_provider_model(config, MODEL_OUTPUT_MAX_TOKENS)


def create_report_provider_model(config: SemanticRuntimeConfig) -> BaseModelBackend:
    """Build the report-domain backend with room for complete cited tool JSON."""
    return _create_provider_model(config, REPORT_DOMAIN_OUTPUT_MAX_TOKENS)


def project_persona_profile(persona: SemanticPersona) -> ProfileProjection:
    """Produce the documented deterministic MatrAIx prompt projection."""
    ordered = sorted(persona.profile.dimensions.items(), key=lambda item: item[0])
    eligible = tuple(
        (name, value)
        for name, value in ordered
        if value.strip().casefold() not in LOW_INFORMATION_VALUES
    )
    included = eligible[:MAX_PROFILE_ATTRIBUTES]
    lines = [
        "Projection schema: matraix-semantic-profile/v1",
        f"Attributes included: {len(included)}",
        f"Informative attributes available: {len(eligible)}",
        f"Total frozen attributes: {len(ordered)}",
    ]
    lines.extend(f"- {name}: {value}" for name, value in included)
    return ProfileProjection(
        text="\n".join(lines),
        included_count=len(included),
        eligible_count=len(eligible),
        total_count=len(ordered),
    )


def _artifact_path(artifact_root: Path, execution: SocialSimulationExecution) -> Path:
    directory = artifact_root / str(execution.id)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OasisExecutionError(
            f"cannot create simulation artifact directory for {execution.id}"
        ) from error
    path = directory / f"{execution.id}.sqlite3"
    if path.exists():
        raise ArtifactConflictError(
            f"refusing to overwrite simulation artifact for run {execution.id}"
        )
    return path


def _seed_runtime(seed: int) -> None:
    random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
    except ImportError:
        return


def _audience_agent(
    execution: SocialSimulationExecution,
    persona: SemanticPersona,
    model_backend: BaseModelBackend,
    graph: AgentGraph,
) -> StrictSocialAgent:
    projection = project_persona_profile(persona)
    user_info = UserInfo(
        user_name=f"persona_{persona.position:03d}",
        name=persona.display_name,
        description=(
            f"SandOwl synthetic persona {persona.persona_id} from {persona.source}; "
            f"profile_sha256={persona.profile_sha256}"
        ),
        profile={
            "display_name": persona.display_name,
            "source": persona.source,
            "profile_sha256": persona.profile_sha256,
            "profile_projection": projection.text,
            "decision_question": execution.decision_question,
        },
        recsys_type="reddit",
        is_controllable=False,
    )
    agent = StrictSocialAgent(
        agent_id=persona.position,
        user_info=user_info,
        user_info_template=PROFILE_TEMPLATE,
        model=model_backend,
        agent_graph=graph,
        available_actions=list(ALLOWED_AUDIENCE_ACTIONS),
        max_iteration=1,
    )
    agent.env = BoundedSemanticEnvironment(agent.env.action)
    return agent


def _scenario_agent(
    execution: SocialSimulationExecution,
    graph: AgentGraph,
) -> SocialAgent:
    agent_id = execution.cohort.persona_count
    user_info = UserInfo(
        user_name=execution.actor_user_name,
        name=execution.actor_name,
        description=execution.actor_bio,
        profile=None,
        recsys_type="reddit",
        is_controllable=True,
    )
    return SocialAgent(
        agent_id=agent_id,
        user_info=user_info,
        model=StubModel(model_type=ModelType.STUB),
        agent_graph=graph,
        available_actions=[ActionType.CREATE_POST],
    )


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def _last_trace_rowid(path: Path) -> int:
    with _connect_sqlite(path) as connection:
        row = connection.execute("SELECT coalesce(max(rowid), 0) AS rowid FROM trace").fetchone()
    if row is None:
        raise ArtifactVerificationError("cannot read OASIS trace cursor")
    return int(row["rowid"])


def _parse_info(raw: object, rowid: int) -> dict[str, object]:
    if not isinstance(raw, str):
        raise ArtifactVerificationError(f"trace row {rowid} info is not JSON text")
    try:
        payload: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ArtifactVerificationError(f"trace row {rowid} info is invalid JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ArtifactVerificationError(f"trace row {rowid} info is not an object")
    return {str(key): value for key, value in payload.items()}


def _require_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactVerificationError(f"expected non-empty text at {location}")
    return value


def _require_positive_int(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArtifactVerificationError(f"expected positive integer at {location}")
    return value


def _exact_keys(info: Mapping[str, object], keys: set[str], rowid: int) -> None:
    if set(info) != keys:
        raise ArtifactVerificationError(
            f"trace row {rowid} info keys mismatch: expected {sorted(keys)}, "
            f"observed {sorted(info)}"
        )


def _normalize_trace(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    execution: SocialSimulationExecution,
    round_number: int,
    phase: str,
) -> TraceObservation:
    rowid = int(row["rowid"])
    user_id = row["user_id"]
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ArtifactVerificationError(f"trace row {rowid} has invalid user_id")
    action = _require_string(row["action"], f"trace[{rowid}].action")
    if action not in {item.value for item in ALLOWED_AUDIENCE_ACTIONS}:
        raise ArtifactVerificationError(f"trace row {rowid} has unsupported action {action!r}")
    observed_at = _require_string(row["created_at"], f"trace[{rowid}].created_at")
    info = _parse_info(row["info"], rowid)
    scenario_position = execution.cohort.persona_count
    if phase == "intervention":
        if user_id != scenario_position:
            raise ArtifactVerificationError(f"trace row {rowid} is not from the scenario actor")
        actor_kind = "scenario"
        persona_id = None
        public_agent_position = 0
    else:
        if not 0 <= user_id < execution.cohort.persona_count:
            raise ArtifactVerificationError(f"trace row {rowid} is not from an audience agent")
        actor_kind = "persona"
        persona_id = execution.cohort.personas[user_id].id
        public_agent_position = user_id + 1

    content: str | None = None
    post_id: str | None = None
    comment_id: str | None = None
    target_post_id: str | None = None
    if action == ActionType.CREATE_POST.value:
        _exact_keys(info, {"content", "post_id"}, rowid)
        content = _require_string(info["content"], f"trace[{rowid}].info.content")
        post_id = str(_require_positive_int(info["post_id"], f"trace[{rowid}].info.post_id"))
    elif action == ActionType.CREATE_COMMENT.value:
        _exact_keys(info, {"content", "comment_id"}, rowid)
        content = _require_string(info["content"], f"trace[{rowid}].info.content")
        raw_comment_id = _require_positive_int(
            info["comment_id"], f"trace[{rowid}].info.comment_id"
        )
        comment_id = str(raw_comment_id)
        comment_row = connection.execute(
            "SELECT post_id FROM comment WHERE comment_id = ?", (raw_comment_id,)
        ).fetchone()
        if comment_row is None:
            raise ArtifactVerificationError(f"trace row {rowid} references missing comment")
        target_post_id = str(
            _require_positive_int(comment_row["post_id"], f"comment[{raw_comment_id}].post_id")
        )
    elif action == ActionType.LIKE_POST.value:
        _exact_keys(info, {"post_id", "like_id"}, rowid)
        target_post_id = str(_require_positive_int(info["post_id"], f"trace[{rowid}].info.post_id"))
        _require_positive_int(info["like_id"], f"trace[{rowid}].info.like_id")
    elif action == ActionType.DISLIKE_POST.value:
        _exact_keys(info, {"post_id", "dislike_id"}, rowid)
        target_post_id = str(_require_positive_int(info["post_id"], f"trace[{rowid}].info.post_id"))
        _require_positive_int(info["dislike_id"], f"trace[{rowid}].info.dislike_id")
    else:
        _exact_keys(info, set(), rowid)

    event = SemanticEvent(
        round=round_number,
        phase=phase,
        actor_kind=actor_kind,
        persona_id=persona_id,
        agent_position=public_agent_position,
        action_type=action,
        content=content,
        post_id=post_id,
        comment_id=comment_id,
        target_post_id=target_post_id,
        observed_at_raw=observed_at,
    )
    return TraceObservation(rowid=rowid, event=event)


def _new_observations(
    path: Path,
    after_rowid: int,
    execution: SocialSimulationExecution,
    round_number: int,
    phase: str,
) -> tuple[TraceObservation, ...]:
    with _connect_sqlite(path) as connection:
        rows = connection.execute(
            "SELECT rowid, user_id, created_at, action, info FROM trace "
            "WHERE rowid > ? AND action IN (?, ?, ?, ?, ?) ORDER BY rowid",
            (
                after_rowid,
                ActionType.CREATE_POST.value,
                ActionType.CREATE_COMMENT.value,
                ActionType.LIKE_POST.value,
                ActionType.DISLIKE_POST.value,
                ActionType.DO_NOTHING.value,
            ),
        ).fetchall()
        return tuple(
            _normalize_trace(connection, row, execution, round_number, phase) for row in rows
        )


def _verify_users(path: Path, execution: SocialSimulationExecution) -> None:
    expected = [
        (
            persona.position,
            persona.position,
            f"persona_{persona.position:03d}",
            persona.display_name,
            (
                f"SandOwl synthetic persona {persona.persona_id} from {persona.source}; "
                f"profile_sha256={persona.profile_sha256}"
            ),
        )
        for persona in execution.cohort.personas
    ]
    scenario_id = execution.cohort.persona_count
    expected.append(
        (
            scenario_id,
            scenario_id,
            execution.actor_user_name,
            execution.actor_name,
            execution.actor_bio,
        )
    )
    with _connect_sqlite(path) as connection:
        rows = connection.execute(
            "SELECT user_id, agent_id, user_name, name, bio FROM user ORDER BY user_id"
        ).fetchall()
    observed = [tuple(row) for row in rows]
    if observed != expected:
        raise ArtifactVerificationError("persisted OASIS users do not match frozen personas")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as error:
        raise ArtifactVerificationError("cannot hash semantic SQLite artifact") from error
    if size <= 0:
        raise ArtifactVerificationError("semantic SQLite artifact is empty")
    return digest.hexdigest(), size


def _verify_artifact(
    path: Path,
    execution: SocialSimulationExecution,
    observations: Sequence[TraceObservation],
) -> SemanticSuccess:
    _verify_users(path, execution)
    events = tuple(item.event for item in observations)
    with _connect_sqlite(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ArtifactVerificationError("semantic SQLite integrity_check failed")
        action_rows = connection.execute(
            "SELECT rowid, user_id, created_at, action, info FROM trace "
            "WHERE action IN (?, ?, ?, ?, ?) ORDER BY rowid",
            tuple(item.value for item in ALLOWED_AUDIENCE_ACTIONS),
        ).fetchall()
        observed_rowids = tuple(int(row["rowid"]) for row in action_rows)
        expected_rowids = tuple(item.rowid for item in observations)
        if observed_rowids != expected_rowids:
            raise ArtifactVerificationError("semantic events do not cover every action trace")
        post_count = int(connection.execute("SELECT count(*) FROM post").fetchone()[0])
        comment_rows = int(connection.execute("SELECT count(*) FROM comment").fetchone()[0])
        like_rows = int(connection.execute('SELECT count(*) FROM "like"').fetchone()[0])
        dislike_rows = int(connection.execute("SELECT count(*) FROM dislike").fetchone()[0])

    initial_events = tuple(event for event in events if event.phase == "intervention")
    expected_interventions = execution.initial_posts
    if tuple(event.content for event in initial_events) != tuple(
        item.content for item in expected_interventions
    ):
        raise ArtifactVerificationError("persisted initial interventions differ from frozen input")
    generated_post_count = sum(
        event.phase == "audience" and event.action_type == "create_post" for event in events
    )
    comment_count = sum(event.action_type == "create_comment" for event in events)
    reaction_count = sum(event.action_type in {"like_post", "dislike_post"} for event in events)
    do_nothing_count = sum(event.action_type == "do_nothing" for event in events)
    initial_post_count = len(initial_events)
    if post_count != initial_post_count + generated_post_count:
        raise ArtifactVerificationError("semantic post table count does not match typed events")
    if comment_rows != comment_count or like_rows + dislike_rows != reaction_count:
        raise ArtifactVerificationError(
            "semantic interaction table counts do not match typed events"
        )
    expected_audience_actions = execution.rounds * execution.cohort.persona_count
    if len(events) != initial_post_count + expected_audience_actions:
        raise ArtifactVerificationError("semantic action count does not match rounds and cohort")
    artifact_sha256, artifact_size_bytes = _hash_file(path)
    return SemanticSuccess(
        engine_version=EXPECTED_OASIS_VERSION,
        camel_version=EXPECTED_CAMEL_VERSION,
        model_name=execution.model_name,
        semantic_config_sha256=execution.semantic_config_sha256,
        prompt_schema_version=execution.prompt_schema_version,
        artifact_sha256=artifact_sha256,
        artifact_size_bytes=artifact_size_bytes,
        user_count=execution.cohort.persona_count + 1,
        initial_post_count=initial_post_count,
        generated_post_count=generated_post_count,
        comment_count=comment_count,
        reaction_count=reaction_count,
        do_nothing_count=do_nothing_count,
        observed_action_count=len(events),
        rounds_completed=execution.rounds,
        limitations=SEMANTIC_LIMITATIONS,
    )


def execution_from_semantic_trial(trial: ClaimedSemanticTrial) -> SocialSimulationExecution:
    """Adapt the legacy comparison experiment at its execution boundary only."""
    actor_key = str(trial.scenario_variant_id).replace("-", "")[:16]
    return SocialSimulationExecution(
        id=trial.id,
        context_id=trial.experiment.id,
        context_kind="semantic_experiment",
        decision_question=trial.experiment.decision_question,
        actor_user_name=f"scenario_{actor_key}",
        actor_name=f"Scenario actor {trial.scenario_position}",
        actor_bio=(
            f"Synthetic intervention actor for scenario {trial.experiment.scenario_id}; "
            f"variant position {trial.scenario_position}."
        ),
        seed=trial.seed,
        rounds=trial.experiment.rounds,
        minutes_per_round=trial.experiment.minutes_per_round,
        model_name=trial.experiment.model_name,
        semantic_config_sha256=trial.experiment.semantic_config_sha256,
        prompt_schema_version=trial.experiment.prompt_schema_version,
        initial_posts=trial.selected_variant.interventions,
        cohort=trial.cohort,
    )


async def run_social_simulation(
    execution: SocialSimulationExecution,
    artifact_root: Path,
    model_backend: BaseModelBackend,
    append_round: Callable[[int, Sequence[SemanticEvent]], None],
) -> SemanticSuccess:
    """Execute one native social simulation without comparison or variant semantics."""
    database_path = _artifact_path(artifact_root, execution)
    _seed_runtime(execution.seed)
    graph = AgentGraph()
    environment = None
    primary_error: Exception | None = None
    observations: list[TraceObservation] = []
    injected_positions: set[int] = set()
    try:
        audience = tuple(
            _audience_agent(execution, persona, model_backend, graph)
            for persona in execution.cohort.personas
        )
        for agent in audience:
            graph.add_agent(agent)
        scenario = _scenario_agent(execution, graph)
        graph.add_agent(scenario)
        environment = make(
            agent_graph=graph,
            platform=DefaultPlatformType.REDDIT,
            database_path=str(database_path),
            semaphore=execution.cohort.persona_count,
        )
        await environment.reset()
        _verify_users(database_path, execution)
        trace_cursor = _last_trace_rowid(database_path)
        for round_number in range(1, execution.rounds + 1):
            round_observations: list[TraceObservation] = []
            due = tuple(
                item
                for item in execution.initial_posts
                if item.position not in injected_positions
                and max(
                    1,
                    (item.offset_minutes + execution.minutes_per_round - 1)
                    // execution.minutes_per_round,
                )
                == round_number
            )
            for intervention in due:
                await environment.step(
                    {
                        scenario: ManualAction(
                            action_type=ActionType.CREATE_POST,
                            action_args={"content": intervention.content},
                        )
                    }
                )
                new_items = _new_observations(
                    database_path, trace_cursor, execution, round_number, "intervention"
                )
                if len(new_items) != 1:
                    raise OasisExecutionError(
                        f"semantic intervention {intervention.position} produced "
                        f"{len(new_items)} successful traces"
                    )
                trace_cursor = new_items[-1].rowid
                round_observations.extend(new_items)
                injected_positions.add(intervention.position)
            await environment.step({agent: LLMAction() for agent in audience})
            audience_items = _new_observations(
                database_path, trace_cursor, execution, round_number, "audience"
            )
            if len(audience_items) != execution.cohort.persona_count:
                raise OasisExecutionError(
                    f"semantic round {round_number} requires exactly one successful trace per "
                    f"audience agent; expected {execution.cohort.persona_count}, "
                    f"observed {len(audience_items)}"
                )
            observed_agents = tuple(sorted(item.event.agent_position for item in audience_items))
            if observed_agents != tuple(range(1, execution.cohort.persona_count + 1)):
                raise OasisExecutionError(
                    f"semantic round {round_number} does not contain one trace per audience agent"
                )
            trace_cursor = audience_items[-1].rowid
            round_observations.extend(audience_items)
            append_round(round_number, tuple(item.event for item in round_observations))
            observations.extend(round_observations)
        if len(injected_positions) != len(execution.initial_posts):
            raise OasisExecutionError("simulation ended before every initial post was injected")
    except Exception as error:
        primary_error = error
        if isinstance(
            error,
            (ArtifactConflictError, ArtifactVerificationError, OasisExecutionError),
        ):
            raise
        raise OasisExecutionError(
            f"OASIS social simulation failed for run {execution.id} with {type(error).__name__}"
        ) from error
    finally:
        cleanup_error: Exception | None = None
        if environment is not None:
            try:
                await environment.close()
            except Exception as error:
                cleanup_error = error
        try:
            graph.close()
        except Exception as error:
            if cleanup_error is None:
                cleanup_error = error
        if primary_error is None and cleanup_error is not None:
            raise OasisExecutionError(
                f"OASIS social simulation cleanup failed for run {execution.id} with "
                f"{type(cleanup_error).__name__}"
            ) from cleanup_error
    return _verify_artifact(database_path, execution, tuple(observations))


async def run_semantic_trial(
    trial: ClaimedSemanticTrial,
    artifact_root: Path,
    model_backend: BaseModelBackend,
    append_round: Callable[[int, Sequence[SemanticEvent]], None],
) -> SemanticSuccess:
    """Run one legacy experiment trial through the shared native execution core."""
    return await run_social_simulation(
        execution_from_semantic_trial(trial),
        artifact_root,
        model_backend,
        append_round,
    )
