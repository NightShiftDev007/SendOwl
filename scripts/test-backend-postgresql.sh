#!/bin/sh
set -eu

readonly test_env_file="${SENDOWL_ENV_FILE:-.env.example}"

cleanup() {
  readonly test_status="$?"
  trap - EXIT
  if ! docker compose --env-file "$test_env_file" --profile test stop postgres-test; then
    echo "Failed to stop the dedicated PostgreSQL test service." >&2
    exit 1
  fi
  exit "$test_status"
}

trap cleanup EXIT

docker compose \
  --env-file "$test_env_file" \
  --profile test \
  up \
  --build \
  --abort-on-container-exit \
  --exit-code-from backend-postgres-test \
  backend-postgres-test
