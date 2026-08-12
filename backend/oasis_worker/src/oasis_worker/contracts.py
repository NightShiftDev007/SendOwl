from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SchemaVersion = Literal["oasis-manual-smoke/v1"]
RunId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", strict=True),
]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, strict=True)]
UserName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$", strict=True),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", strict=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ActorSpec(StrictModel):
    agent_id: Literal[0]
    user_name: UserName
    name: Annotated[RequiredText, Field(max_length=200)]
    bio: Annotated[RequiredText, Field(max_length=500)]


class PostSpec(StrictModel):
    content: Annotated[RequiredText, Field(max_length=4000)]


class JobSpec(StrictModel):
    schema_version: SchemaVersion
    run_id: RunId
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    output_directory: RequiredText
    actor: ActorSpec
    posts: Annotated[tuple[PostSpec, ...], Field(min_length=1, max_length=20)]

    @field_validator("output_directory")
    @classmethod
    def require_absolute_output_directory(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("output_directory must be an absolute path")
        if "\x00" in value:
            raise ValueError("output_directory must not contain a NUL byte")
        return value


class ArtifactResult(StrictModel):
    database_path: RequiredText
    sha256: Sha256
    size_bytes: Annotated[int, Field(gt=0)]


class ObservedUser(StrictModel):
    user_id: Literal[0]
    agent_id: Literal[0]
    user_name: UserName
    name: RequiredText
    bio: RequiredText
    created_at: RequiredText


class ObservedPost(StrictModel):
    post_id: Annotated[int, Field(gt=0)]
    user_id: Literal[0]
    content: RequiredText
    created_at: RequiredText


class SignupTraceInfo(StrictModel):
    name: RequiredText
    user_name: UserName
    bio: RequiredText


class CreatePostTraceInfo(StrictModel):
    content: RequiredText
    post_id: Annotated[int, Field(gt=0)]


class SignupTrace(StrictModel):
    position: Literal[0]
    user_id: Literal[0]
    created_at: RequiredText
    action: Literal["sign_up"]
    info: SignupTraceInfo


class CreatePostTrace(StrictModel):
    position: Annotated[int, Field(gt=0)]
    user_id: Literal[0]
    created_at: RequiredText
    action: Literal["create_post"]
    info: CreatePostTraceInfo


ObservedTrace = SignupTrace | CreatePostTrace


class ObservedState(StrictModel):
    user: ObservedUser
    posts: tuple[ObservedPost, ...]
    traces: tuple[ObservedTrace, ...]


class JobResult(StrictModel):
    schema_version: SchemaVersion
    run_id: RunId
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    engine: Literal["camel-oasis"]
    engine_version: Literal["0.2.5"]
    camel_version: Literal["0.2.78"]
    mode: Literal["reddit_manual_smoke"]
    artifact: ArtifactResult
    observed: ObservedState
    limitations: tuple[RequiredText, ...]


class ErrorBody(StrictModel):
    type: RequiredText
    message: RequiredText


class ErrorResult(StrictModel):
    error: ErrorBody
