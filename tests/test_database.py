import shutil
import sqlite3
from pathlib import Path

import pytest

from payroll_validation.config import DATA_DIR
from payroll_validation.database.connection import connect
from payroll_validation.database.init_db import initialize, verify_database
from payroll_validation.generators.generate_dataset import generate_dataset


CORE_ENTITIES = (
    "employees", "pay_groups", "pay_periods", "time_entries", "leave_records",
    "allowances", "deductions", "payroll_inputs", "validation_rules", "exceptions",
    "approvals", "payroll_exports",
)


def test_schema_contains_required_entities():
    schema = Path(__file__).parents[1] / "src" / "payroll_validation" / "database" / "schema.sql"
    sql = schema.read_text(encoding="utf-8").lower()
    for entity in CORE_ENTITIES:
        assert f"create table if not exists {entity}" in sql


def test_migration_preserves_existing_payroll_rows_and_backfills_relationships(tmp_path):
    source = DATA_DIR / "payroll.db"
    if not source.exists():
        pytest.skip("Configured starter database is not present")
    target = tmp_path / "payroll-migration-copy.db"
    shutil.copy2(source, target)
    with connect(target) as db:
        before = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in ("employees", "pay_periods", "time_entries", "allowances", "deductions", "payroll_inputs", "payroll_results")
        }

    result = initialize(target)
    with connect(target) as db:
        after = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in before
        }
        assert after == before
        assert db.execute("SELECT COUNT(*) FROM employee_pay_group_assignments").fetchone()[0] == before["employees"]
        assert db.execute("SELECT COUNT(*) FROM payroll_results WHERE payroll_run_input_id IS NOT NULL").fetchone()[0] == before["payroll_results"]
        assert not list(db.execute("PRAGMA foreign_key_check"))
    assert result["table_count"] == 21
    assert result["relationship_errors"] == 0


def test_effective_assignment_bridge_and_payroll_result_one_to_one(tmp_path):
    db_path = tmp_path / "generated-starter.db"
    generate_dataset("starter", database_path=db_path, output_dir=tmp_path / "generated")
    result = verify_database(db_path)
    assert result["foreign_key_count"] == 39
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == db.execute(
            "SELECT COUNT(DISTINCT employee_id) FROM employee_pay_group_assignments"
        ).fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM payroll_results").fetchone()[0] == db.execute(
            "SELECT COUNT(DISTINCT payroll_run_input_id) FROM payroll_results"
        ).fetchone()[0]
        assignment = db.execute(
            "SELECT employee_id,pay_group_id,effective_from FROM employee_pay_group_assignments LIMIT 1"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError, match="assignments cannot overlap"):
            db.execute(
                "INSERT INTO employee_pay_group_assignments(employee_id,pay_group_id,effective_from,status) VALUES (?,?,?,'active')",
                tuple(assignment),
            )

        result_pair = db.execute(
            "SELECT payroll_result_id,payroll_run_input_id FROM payroll_results ORDER BY payroll_result_id LIMIT 2"
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError, match="must match its unique run input"):
            db.execute(
                "UPDATE payroll_results SET payroll_run_input_id=? WHERE payroll_result_id=?",
                (result_pair[1]["payroll_run_input_id"], result_pair[0]["payroll_result_id"]),
            )
        employee_id = db.execute("SELECT employee_id FROM employees LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="identifiers are immutable"):
            db.execute("UPDATE employees SET employee_id=employee_id+1000000 WHERE employee_id=?", (employee_id,))
        db.execute(
            "INSERT INTO audit_events(entity_type,entity_id,action,actor) VALUES ('employee','test','created','pytest')"
        )
        event_id = db.execute("SELECT MAX(audit_event_id) FROM audit_events").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="audit events are append-only"):
            db.execute("UPDATE audit_events SET action='rewritten' WHERE audit_event_id=?", (event_id,))
        with pytest.raises(sqlite3.IntegrityError, match="audit events are append-only"):
            db.execute("DELETE FROM audit_events WHERE audit_event_id=?", (event_id,))
