"""Strict runtime configuration validation tests."""

import pytest

from app.config import ConfigurationError, load_runtime_settings


@pytest.mark.parametrize(
    ("environment", "expected_message"),
    [
        ({"APP_ENV": "local"}, "APP_ENV must be one of"),
        ({"DATABASE_URL": "sqlite:///local.db"}, "DATABASE_URL must be a PostgreSQL URL"),
        ({"DATABASE_URL": "postgresql://db:5432"}, "must include a database name"),
        ({"REDIS_URL": "http://redis:6379/0"}, "REDIS_URL must be a Redis URL"),
        ({"REDIS_URL": ""}, "REDIS_URL is present but empty"),
    ],
)
def test_runtime_settings_reject_invalid_explicit_values(
    environment: dict[str, str],
    expected_message: str,
) -> None:
    with pytest.raises(ConfigurationError, match=expected_message):
        load_runtime_settings(environment)
