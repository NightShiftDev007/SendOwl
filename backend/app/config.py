"""Explicit runtime configuration loading and validation."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated

from pydantic import AnyUrl, BaseModel, ConfigDict, TypeAdapter, UrlConstraints, ValidationError


class ConfigurationError(ValueError):
    """Raised when a configured environment value is invalid."""


class ApplicationEnvironment(StrEnum):
    """Supported deployment environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


type DatabaseUrl = Annotated[
    AnyUrl,
    UrlConstraints(
        allowed_schemes=["postgresql", "postgresql+asyncpg", "postgresql+psycopg"],
        host_required=True,
    ),
]
type RedisUrl = Annotated[
    AnyUrl,
    UrlConstraints(
        allowed_schemes=["redis", "rediss"],
        host_required=True,
    ),
]


class RuntimeSettings(BaseModel):
    """Validated configuration that distinguishes absence from invalid values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    app_env: ApplicationEnvironment | None
    database_url: DatabaseUrl | None
    redis_url: RedisUrl | None


def read_optional_environment_value(
    environment: Mapping[str, str],
    variable_name: str,
) -> str | None:
    """Read one optional variable while rejecting explicitly empty values."""
    value = environment.get(variable_name)
    if value is None:
        return None
    if not value:
        raise ConfigurationError(
            f"{variable_name} is present but empty; remove it or provide a valid value"
        )
    return value


def parse_application_environment(value: str | None) -> ApplicationEnvironment | None:
    """Parse APP_ENV without coercion or an implicit default."""
    if value is None:
        return None
    try:
        return ApplicationEnvironment(value)
    except ValueError as error:
        supported_values = ", ".join(environment.value for environment in ApplicationEnvironment)
        raise ConfigurationError(
            f"APP_ENV must be one of [{supported_values}]; received {value!r}"
        ) from error


def parse_database_url(value: str | None) -> DatabaseUrl | None:
    """Validate DATABASE_URL without opening a database connection."""
    if value is None:
        return None
    try:
        database_url = TypeAdapter(DatabaseUrl).validate_python(value)
    except ValidationError as error:
        raise ConfigurationError(
            "DATABASE_URL must be a PostgreSQL URL with an explicit host"
        ) from error
    if database_url.path in (None, "", "/"):
        raise ConfigurationError("DATABASE_URL must include a database name")
    return database_url


def parse_redis_url(value: str | None) -> RedisUrl | None:
    """Validate REDIS_URL without opening a Redis connection."""
    if value is None:
        return None
    try:
        return TypeAdapter(RedisUrl).validate_python(value)
    except ValidationError as error:
        raise ConfigurationError("REDIS_URL must be a Redis URL with an explicit host") from error


def load_runtime_settings(environment: Mapping[str, str]) -> RuntimeSettings:
    """Load the complete supported configuration surface from an explicit mapping."""
    app_env = parse_application_environment(read_optional_environment_value(environment, "APP_ENV"))
    database_url = parse_database_url(read_optional_environment_value(environment, "DATABASE_URL"))
    redis_url = parse_redis_url(read_optional_environment_value(environment, "REDIS_URL"))
    return RuntimeSettings(
        app_env=app_env,
        database_url=database_url,
        redis_url=redis_url,
    )
