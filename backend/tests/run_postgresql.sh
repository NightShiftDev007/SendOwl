#!/bin/sh
set -eu

alembic upgrade head
pytest -p no:cacheprovider \
  tests/test_evidence_bundles_postgresql.py::test_evidence_bundle_api_projects_sealed_world_snapshot \
  tests/test_matraix_batch_postgresql.py::test_matraix_batch_registry_executes_against_postgresql \
  tests/test_matraix_chat_postgresql.py::test_matraix_chat_api_and_guards_execute_against_postgresql \
  tests/test_matraix_linux_postgresql.py::test_matraix_linux_retry_executes_against_postgresql \
  tests/test_matraix_trial_archive_postgresql.py::test_matraix_trial_archive_executes_against_postgresql \
  tests/test_matraix_web_postgresql.py::test_matraix_web_api_and_guards_execute_against_postgresql \
  tests/test_media_importer.py::test_postgresql_identity_lock_and_migration_guard \
  tests/test_media_sync.py::test_postgresql_media_sync_skips_overlapping_runs \
  tests/test_media_sync.py::test_postgresql_rejects_failed_run_with_next_schedule \
  tests/test_media_sync.py::test_postgresql_failed_refresh_preserves_media_snapshot \
  tests/test_media_sync.py::test_postgresql_cancelled_refresh_is_terminal_and_releases_lock \
  tests/test_media_sync.py::test_postgresql_lock_release_failure_preserves_primary_error \
  tests/test_media_sync.py::test_postgresql_committed_success_survives_lock_release_failure \
  tests/test_migrations.py::test_postgresql_content_addresses_are_enforced_when_resources_are_sealed \
  tests/test_migrations.py::test_population_child_write_waits_for_concurrent_dataset_seal \
  tests/test_migrations.py::test_semantic_postgresql_guards_verify_events_progress_and_results \
  tests/test_migrations.py::test_semantic_http_endpoints_execute_against_postgresql \
  tests/test_populations_postgresql.py::test_population_repository_uses_sealed_postgresql_resources
