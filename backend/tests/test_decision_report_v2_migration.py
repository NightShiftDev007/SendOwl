"""Isolated contract checks for the DecisionReport V2 migration."""

from importlib import import_module
from typing import Any


def test_decision_report_v2_migration_preserves_constraint_call_order_and_seal_payload_guard(
    monkeypatch: Any,
) -> None:
    migration = import_module("migrations.versions.20260816_core_0042_decision_report_v2")
    operations: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def record(operation: str):
        def recorder(*args: object, **kwargs: object) -> None:
            operations.append((operation, args, kwargs))

        return recorder

    for operation in (
        "add_column",
        "create_foreign_key",
        "drop_constraint",
        "create_unique_constraint",
        "create_check_constraint",
        "drop_column",
        "execute",
    ):
        monkeypatch.setattr(migration.op, operation, record(operation))

    migration.upgrade()

    upgrade_checks = {
        args[0]: args
        for operation, args, _kwargs in operations
        if operation == "create_check_constraint"
    }
    assert upgrade_checks["ck_decision_reports_generator"][1] == "decision_reports"
    assert upgrade_checks["ck_decision_reports_snapshot_identity"][1] == "decision_reports"
    assert upgrade_checks["ck_decision_report_sections_position"][1] == "decision_report_sections"
    assert upgrade_checks["ck_decision_report_sections_kind"][1] == "decision_report_sections"
    assert upgrade_checks["ck_decision_report_sections_data"][1] == "decision_report_sections"

    upgrade_sql = [
        args[0] for operation, args, _kwargs in operations if operation == "execute" and args
    ]
    assert any(
        "actual.data_json::jsonb ->> 'payload_kind'" in statement
        for statement in upgrade_sql
        if isinstance(statement, str)
    )

    operations.clear()
    migration.downgrade()

    downgrade_checks = {
        args[0]: args
        for operation, args, _kwargs in operations
        if operation == "create_check_constraint"
    }
    assert downgrade_checks["ck_decision_report_sections_kind"][1] == "decision_report_sections"
    assert downgrade_checks["ck_decision_report_sections_position"][1] == "decision_report_sections"
    assert downgrade_checks["ck_decision_reports_generator"][1] == "decision_reports"
