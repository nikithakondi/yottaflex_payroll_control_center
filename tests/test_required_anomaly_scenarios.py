"""End-to-end coverage for the five planted payroll blocking scenarios."""
import re

import pytest

from payroll_validation.database.connection import connect
from payroll_validation.services.payroll_service import export_payroll_run
from payroll_validation.validators.validation_service import validate_payroll_run


SCENARIOS = (
    ("hours", "HOURS_PERIOD_MAX", "time_entries", "source", "anomaly_hours_over_max"),
    ("allowance", "DUPLICATE_ALLOWANCE", "allowances", "submission_type", "duplicate"),
    ("unapproved_time", "TIME_UNAPPROVED", "time_entries", "source", "anomaly_unapproved_time"),
    ("leave_deduction", "DUP_UNPAID_LEAVE_DEDUCTION", "deductions", "submission_type", "duplicate"),
    ("reconciliation", "PAYROLL_RECONCILIATION", "payroll_results", "calculation_details", "payroll_totals_fail_reconciliation"),
)


def _scenario_rows(db, scenario):
    if scenario == "hours":
        rows = list(db.execute(
            "SELECT * FROM time_entries WHERE source='anomaly_hours_over_max' ORDER BY time_entry_id"
        ))
    elif scenario == "allowance":
        original = db.execute(
            "SELECT source_reference FROM allowances WHERE submission_type='duplicate' ORDER BY allowance_id LIMIT 1"
        ).fetchone()
        rows = list(db.execute(
            "SELECT * FROM allowances WHERE source_reference=? ORDER BY allowance_id",
            (original["source_reference"],),
        ))
    elif scenario == "unapproved_time":
        rows = list(db.execute(
            "SELECT * FROM time_entries WHERE source='anomaly_unapproved_time' ORDER BY time_entry_id"
        ))
    elif scenario == "leave_deduction":
        duplicate = db.execute(
            "SELECT leave_id FROM deductions WHERE submission_type='duplicate' AND leave_id IS NOT NULL ORDER BY deduction_id LIMIT 1"
        ).fetchone()
        rows = list(db.execute(
            "SELECT * FROM deductions WHERE leave_id=? ORDER BY deduction_id", (duplicate["leave_id"],)
        ))
    else:
        rows = list(db.execute(
            "SELECT * FROM payroll_results WHERE json_extract(calculation_details,'$.anomaly_label')='payroll_totals_fail_reconciliation'"
        ))
    assert rows, f"No deterministic record found for scenario {scenario}"
    return [dict(row) for row in rows]


def _source_rows_for_employee_period(db, scenario_rows, scenario):
    if scenario != "reconciliation":
        return scenario_rows
    result = scenario_rows[0]
    period_id = db.execute(
        "SELECT pay_period_id FROM payroll_runs WHERE payroll_run_id=?", (result["payroll_run_id"],)
    ).fetchone()[0]
    employee_id = result["employee_id"]
    snapshots = {}
    for table, key in (("time_entries", "time_entry_id"), ("leave_records", "leave_id"),
                       ("allowances", "allowance_id"), ("deductions", "deduction_id")):
        snapshots[table] = [dict(row) for row in db.execute(
            f"SELECT * FROM {table} WHERE employee_id=? AND pay_period_id=? ORDER BY {key}",
            (employee_id, period_id),
        )]
    snapshots["payroll_results"] = scenario_rows
    return snapshots


def _assert_scenario_detected_and_export_blocked(database_copy, tmp_path, scenario, rule_code):
    with connect(database_copy) as db:
        rows = _scenario_rows(db, scenario)
        source_before = _source_rows_for_employee_period(db, rows, scenario)
        if scenario == "hours":
            assert rows[0]["regular_hours"] + rows[0]["overtime_hours"] > 200
        elif scenario == "allowance":
            assert len(rows) == 2 and {row["submission_type"] for row in rows} == {"original", "duplicate"}
        elif scenario == "unapproved_time":
            assert rows[0]["approval_status"] != "approved"
        elif scenario == "leave_deduction":
            assert len(rows) == 2 and len({row["leave_id"] for row in rows}) == 1
        else:
            assert "payroll_totals_fail_reconciliation" in rows[0]["calculation_details"]

        if scenario == "reconciliation":
            run_id = rows[0]["payroll_run_id"]
            employee_id = rows[0]["employee_id"]
        else:
            run_id = db.execute(
                "SELECT payroll_run_id FROM payroll_runs WHERE pay_period_id=? ORDER BY run_number LIMIT 1",
                (rows[0]["pay_period_id"],),
            ).fetchone()[0]
            employee_id = rows[0]["employee_id"]
        employee_number = db.execute(
            "SELECT employee_number FROM employees WHERE employee_id=?", (employee_id,)
        ).fetchone()[0]
        period_code = db.execute(
            "SELECT p.pay_period_code FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) WHERE r.payroll_run_id=?",
            (run_id,),
        ).fetchone()[0]

    report = validate_payroll_run(run_id, database_copy, actor="scenario_test")
    assert report["exceptions_by_category"].get(rule_code) == 1
    with connect(database_copy) as db:
        exception = db.execute(
            "SELECT exception_code,employee_reference,pay_period_reference,rule_code,workflow_status "
            "FROM exceptions WHERE payroll_run_id=? AND rule_code=? AND employee_reference=?",
            (run_id, rule_code, employee_number),
        ).fetchone()
        assert exception is not None
        assert re.fullmatch(r"PEX-2026-\d{6}", exception["exception_code"])
        assert exception["employee_reference"] == employee_number
        assert exception["pay_period_reference"] == period_code
        assert exception["workflow_status"] == "open"

    export_path = tmp_path / f"blocked-{scenario}.csv"
    with pytest.raises(ValueError, match="Export blocked: unresolved critical"):
        export_payroll_run(run_id, export_path, database_copy, actor="scenario_test")
    assert not export_path.exists()

    with connect(database_copy) as db:
        rows_after = _scenario_rows(db, scenario)
        source_after = _source_rows_for_employee_period(db, rows_after, scenario)
        assert source_after == source_before, "Validation/export must not rewrite original source records"


def test_hours_over_period_max_creates_exception_and_blocks_export(database_copy, tmp_path):
    _assert_scenario_detected_and_export_blocked(database_copy, tmp_path, "hours", "HOURS_PERIOD_MAX")


def test_duplicate_allowance_creates_exception_and_blocks_export(database_copy, tmp_path):
    _assert_scenario_detected_and_export_blocked(database_copy, tmp_path, "allowance", "DUPLICATE_ALLOWANCE")


def test_unapproved_time_export_attempt_is_blocked(database_copy, tmp_path):
    _assert_scenario_detected_and_export_blocked(database_copy, tmp_path, "unapproved_time", "TIME_UNAPPROVED")


def test_duplicate_unpaid_leave_deduction_creates_exception_and_blocks_export(database_copy, tmp_path):
    _assert_scenario_detected_and_export_blocked(database_copy, tmp_path, "leave_deduction", "DUP_UNPAID_LEAVE_DEDUCTION")


def test_reconciliation_mismatch_creates_exception_and_blocks_export(database_copy, tmp_path):
    _assert_scenario_detected_and_export_blocked(database_copy, tmp_path, "reconciliation", "PAYROLL_RECONCILIATION")
