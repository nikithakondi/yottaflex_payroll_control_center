import csv
import shutil
import sqlite3

import pytest

from payroll_validation.database.connection import connect
from payroll_validation.generators.generate_dataset import generate_dataset
from payroll_validation.services.payroll_service import (
    approve_payroll_run, export_payroll_run, process_payroll_period, record_time_correction,
)
from payroll_validation.validators.validation_service import validate_all_payroll_runs, validate_payroll_run


@pytest.fixture(scope="module")
def starter_template(tmp_path_factory):
    root=tmp_path_factory.mktemp("validation-starter")
    database=root/"starter.db"
    output=root/"generated"
    generate_dataset("starter",database_path=database,output_dir=output)
    return database,output


@pytest.fixture
def database_copy(starter_template,tmp_path):
    source,_=starter_template
    target=tmp_path/"payroll.db"
    shutil.copy2(source,target)
    return target


def _run_for_period(database_path,pay_period_id):
    with connect(database_path) as db:
        return db.execute("SELECT payroll_run_id FROM payroll_runs WHERE pay_period_id=? ORDER BY run_number LIMIT 1",(pay_period_id,)).fetchone()[0]


def test_five_planted_anomalies_are_detected_and_match_test_ground_truth(database_copy,starter_template):
    _,output=starter_template
    report=validate_all_payroll_runs(database_copy,actor="pytest")
    assert report["total_exceptions"]==5
    assert report["exceptions_by_category"]=={
        "HOURS_PERIOD_MAX":1,
        "DUP_UNPAID_LEAVE_DEDUCTION":1,
        "TIME_UNAPPROVED":1,
        "DUPLICATE_ALLOWANCE":1,
        "PAYROLL_RECONCILIATION":1,
    }
    with (output/"ground_truth.csv").open(encoding="utf-8",newline="") as source:
        expected=list(csv.DictReader(source))
    with connect(database_copy) as db:
        actual={row["exception_code"]:row for row in db.execute("SELECT * FROM exceptions")}
    assert len(expected)==5
    for truth in expected:
        exception=actual[truth["anomaly_id"]]
        assert exception["employee_reference"]==truth["employee_id"]
        assert exception["pay_period_reference"]==truth["pay_period_id"]
        assert truth["expected_validation_result"]==f"FAIL:{exception['rule_code']}"
        assert truth["expected_decision"]=="BLOCK_EXPORT"
    import json
    expected_json=json.loads((output/"ground_truth.json").read_text(encoding="utf-8"))
    assert expected_json==expected


def test_missing_bank_account_rule(database_copy):
    with connect(database_copy) as db:
        db.execute("UPDATE employees SET bank_account_token=NULL WHERE employee_number='EMP-000010'")
    report=validate_payroll_run(1,database_copy)
    assert report["exceptions_by_category"]["BANK_DETAILS_MISSING"]==1


def test_missing_tax_information_rule(database_copy):
    with connect(database_copy) as db:
        db.execute("UPDATE employees SET tax_info_token=' ' WHERE employee_number='EMP-000010'")
    report=validate_payroll_run(1,database_copy)
    assert report["exceptions_by_category"]["TAX_INFORMATION_MISSING"]==1


def test_duplicate_time_entry_rule(database_copy):
    with connect(database_copy) as db:
        source=db.execute("SELECT * FROM time_entries WHERE approval_status='approved' AND status='approved' AND submission_type='original' LIMIT 1").fetchone()
        db.execute("INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (source["employee_id"],source["pay_period_id"],source["work_date"],"TIME-2026-99999991",source["regular_hours"],source["overtime_hours"],"test_duplicate","approved","approved","original"))
        run_id=_run_for_period(database_copy,source["pay_period_id"])
    report=validate_payroll_run(run_id,database_copy)
    assert report["exceptions_by_category"]["DUPLICATE_TIME_ENTRY"]>=1


def test_period_hours_max_rule(database_copy):
    report=validate_payroll_run(1,database_copy)
    assert report["exceptions_by_category"]["HOURS_PERIOD_MAX"]==1


def test_duplicate_allowance_rule(database_copy):
    with connect(database_copy) as db:
        period=db.execute("SELECT pay_period_id FROM allowances WHERE submission_type='duplicate'").fetchone()[0]
        run_id=_run_for_period(database_copy,period)
    report=validate_payroll_run(run_id,database_copy)
    assert report["exceptions_by_category"]["DUPLICATE_ALLOWANCE"]==1


def test_unapproved_time_rule(database_copy):
    with connect(database_copy) as db:
        period=db.execute("SELECT pay_period_id FROM time_entries WHERE source='anomaly_unapproved_time'").fetchone()[0]
        run_id=_run_for_period(database_copy,period)
    report=validate_payroll_run(run_id,database_copy)
    assert report["exceptions_by_category"]["TIME_UNAPPROVED"]==1


def test_duplicate_unpaid_leave_deduction_rule(database_copy):
    report=validate_payroll_run(1,database_copy)
    assert report["exceptions_by_category"]["DUP_UNPAID_LEAVE_DEDUCTION"]==1


def test_incorrect_payroll_calculation_rule(database_copy):
    with connect(database_copy) as db:
        db.execute("UPDATE payroll_results SET regular_pay=regular_pay+10 WHERE payroll_run_id=1 AND employee_id=10")
    report=validate_payroll_run(1,database_copy)
    assert report["exceptions_by_category"]["INCORRECT_PAYROLL_CALCULATION"]>=1


def test_payroll_reconciliation_rule(database_copy):
    with connect(database_copy) as db:
        row=db.execute("SELECT payroll_run_id FROM payroll_results WHERE payroll_run_id=3 AND ABS(gross_pay-(regular_pay+overtime_pay+allowance_total))>0.005").fetchone()
        assert row is not None
    report=validate_payroll_run(3,database_copy)
    assert report["exceptions_by_category"]["PAYROLL_RECONCILIATION"]==1


def test_invalid_employee_reference_rule(database_copy):
    raw=sqlite3.connect(database_copy)
    raw.execute("PRAGMA foreign_keys=OFF")
    raw.execute("INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type) VALUES (999999,1,'2026-01-02','TIME-2026-99999992',8,0,'broken_import','submitted','pending','original')")
    raw.commit(); raw.close()
    report=validate_payroll_run(1,database_copy)
    assert report["exceptions_by_category"]["INVALID_REFERENCE"]>=1


def test_invalid_pay_period_reference_rule(database_copy):
    raw=sqlite3.connect(database_copy)
    raw.execute("PRAGMA foreign_keys=OFF")
    raw.execute("INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type) VALUES (1,999999,'2026-01-02','TIME-2026-99999993',8,0,'broken_import','approved','approved','original')")
    raw.commit(); raw.close()
    report=validate_payroll_run(1,database_copy)
    assert report["exceptions_by_category"]["INVALID_REFERENCE"]>=1


def test_clean_records_do_not_raise_exceptions_and_can_be_approved_exported(database_copy,tmp_path):
    with connect(database_copy) as db:
        db.execute("DELETE FROM time_entries WHERE source IN ('anomaly_hours_over_max','anomaly_unapproved_time')")
        db.execute("DELETE FROM allowances WHERE submission_type='duplicate'")
        db.execute("DELETE FROM deductions WHERE submission_type='duplicate'")
        period_id=db.execute("SELECT pay_period_id FROM pay_periods WHERE pay_period_code='PP-2026-03'").fetchone()[0]
    clean_run=process_payroll_period(period_id,database_copy,actor="pytest")
    report=validate_payroll_run(clean_run["payroll_run_id"],database_copy,actor="pytest")
    assert report["total_exceptions"]==0
    approval=approve_payroll_run(clean_run["payroll_run_id"],"test-approver",database_copy)
    assert approval["status"]=="approved"
    exported=export_payroll_run(clean_run["payroll_run_id"],tmp_path/"clean.csv",database_copy,actor="pytest")
    assert exported["record_count"]==100
    assert (tmp_path/"clean.csv").exists()


def test_anomalous_run_cannot_be_approved_or_exported(database_copy,tmp_path):
    with pytest.raises(ValueError,match="approval blocked"):
        approve_payroll_run(1,"test-approver",database_copy)
    with pytest.raises(ValueError,match="Export blocked"):
        export_payroll_run(1,tmp_path/"blocked.csv",database_copy,actor="pytest")
    assert not (tmp_path/"blocked.csv").exists()


def test_unapproved_time_entry_specifically_blocks_export(database_copy,tmp_path):
    with connect(database_copy) as db:
        period=db.execute("SELECT pay_period_id FROM time_entries WHERE source='anomaly_unapproved_time'").fetchone()[0]
        run_id=_run_for_period(database_copy,period)
    with pytest.raises(ValueError,match="Export blocked"):
        export_payroll_run(run_id,tmp_path/"pending-time.csv",database_copy,actor="pytest")
    assert not (tmp_path/"pending-time.csv").exists()


def test_time_correction_is_append_only_and_new_run_revalidates(database_copy):
    with connect(database_copy) as db:
        original=db.execute("SELECT * FROM time_entries WHERE source='anomaly_unapproved_time'").fetchone()
        original_snapshot=(original["status"],original["approval_status"],original["regular_hours"])
        period_id=original["pay_period_id"]
        old_run=_run_for_period(database_copy,period_id)
    first=validate_payroll_run(old_run,database_copy)
    assert first["exceptions_by_category"]["TIME_UNAPPROVED"]==1
    correction=record_time_correction(original["time_entry_id"],8,0,database_copy,actor="pytest")
    with connect(database_copy) as db:
        after=db.execute("SELECT status,approval_status,regular_hours FROM time_entries WHERE time_entry_id=?",(original["time_entry_id"],)).fetchone()
        assert tuple(after)==original_snapshot
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE entity_id=? AND action='correction_added'",(correction["time_entry_code"],)).fetchone()[0]==1
    new_run=process_payroll_period(period_id,database_copy,actor="pytest")
    second=validate_payroll_run(new_run["payroll_run_id"],database_copy,actor="pytest")
    assert second["exceptions_by_category"].get("TIME_UNAPPROVED",0)==0
    assert second["total_exceptions"]==0
