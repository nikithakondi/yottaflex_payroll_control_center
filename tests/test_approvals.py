import shutil

import pytest

from payroll_validation.database.connection import connect
from payroll_validation.generators.generate_dataset import generate_dataset
from payroll_validation.approvals.approval_service import review_payroll_input, submit_time_correction
from payroll_validation.services.exception_service import assign_exception, review_exception
from payroll_validation.services.payroll_service import process_payroll_period, approve_payroll_run
from payroll_validation.validators.validation_service import validate_payroll_run


@pytest.fixture
def workflow_db(tmp_path):
    source = tmp_path / "source.db"
    generate_dataset("starter", database_path=source, output_dir=tmp_path / "generated")
    target = tmp_path / "workflow.db"
    shutil.copy2(source, target)
    return target


def _clean_period(db_path):
    with connect(db_path) as db:
        db.execute("DELETE FROM time_entries WHERE source IN ('anomaly_hours_over_max','anomaly_unapproved_time')")
        db.execute("DELETE FROM allowances WHERE submission_type='duplicate'")
        db.execute("DELETE FROM deductions WHERE submission_type='duplicate'")
        return db.execute("SELECT pay_period_id FROM pay_periods ORDER BY pay_period_id DESC LIMIT 1").fetchone()[0]


def test_successful_approval_and_rejection_are_audited(workflow_db):
    period = _clean_period(workflow_db)
    run = process_payroll_period(period, workflow_db)
    validate_payroll_run(run["payroll_run_id"], workflow_db)
    with connect(workflow_db) as db:
        item = db.execute("SELECT payroll_input_id FROM payroll_inputs WHERE pay_period_id=? LIMIT 1", (period,)).fetchone()[0]
    approved = review_payroll_input(item,"reviewer-1","Manager","Approved","checked",workflow_db,run["payroll_run_id"])
    assert approved["status"] == "approved"
    rejected = review_payroll_input(item,"reviewer-2","HR Partner","Rejected","needs review",workflow_db,run["payroll_run_id"])
    assert rejected["previous_status"] == "approved"
    with connect(workflow_db) as db:
        assert db.execute("SELECT COUNT(*) FROM approval_history WHERE payroll_input_id=?",(item,)).fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE entity_type='payroll_input' AND action LIKE 'approval_%'").fetchone()[0] == 2


def test_correction_required_invalid_approval_block_and_audit(workflow_db):
    with connect(workflow_db) as db:
        item = db.execute("SELECT payroll_input_id FROM payroll_inputs LIMIT 1").fetchone()[0]
    correction = review_payroll_input(item,"manager","Manager","Correction Required","fix source",workflow_db)
    assert correction["status"] == "correction_required"
    # A planted invalid payroll cannot be approved.
    with pytest.raises(ValueError, match="Approval blocked"):
        review_payroll_input(item,"manager","Manager","Approved","approve",workflow_db)
    with connect(workflow_db) as db:
        assert db.execute("SELECT COUNT(*) FROM approval_history WHERE payroll_input_id=?",(item,)).fetchone()[0] == 1


def test_unresolved_exception_blocks_approval_and_exception_assignment_history(workflow_db):
    validate_payroll_run(1,workflow_db)
    with connect(workflow_db) as db:
        exception = db.execute("SELECT exception_id FROM exceptions LIMIT 1").fetchone()[0]
        item = db.execute("SELECT payroll_input_id FROM payroll_inputs WHERE pay_period_id=(SELECT pay_period_id FROM payroll_runs WHERE payroll_run_id=1) LIMIT 1").fetchone()[0]
    assignment = assign_exception(exception,"hr-2","HR Partner","ops-1","System Administrator",workflow_db,"review")
    assert assignment["exception_id"] == exception
    with pytest.raises(ValueError, match="Approval blocked"):
        review_payroll_input(item,"hr-2","HR Partner","Approved","attempt",workflow_db)
    reviewed = review_exception(exception,"hr-2","HR Partner","Resolved","source corrected",workflow_db)
    assert reviewed["workflow_status"] == "resolved"
    with connect(workflow_db) as db:
        assert db.execute("SELECT COUNT(*) FROM exception_review_history WHERE exception_id=?",(exception,)).fetchone()[0] == 1


def test_revalidation_after_append_only_correction_and_role_permissions(workflow_db):
    with connect(workflow_db) as db:
        entry = db.execute("SELECT * FROM time_entries WHERE source='anomaly_unapproved_time'").fetchone()
        item = db.execute("SELECT payroll_input_id FROM payroll_inputs WHERE employee_id=? AND pay_period_id=?",(entry["employee_id"],entry["pay_period_id"])).fetchone()[0]
        original_hours = entry["regular_hours"]
    review_payroll_input(item,"manager","Manager","Correction Required","correct time",workflow_db)
    with pytest.raises(PermissionError):
        submit_time_correction(item,entry["time_entry_id"],8,0,"someone-else",database_path=workflow_db)
    result = submit_time_correction(item,entry["time_entry_id"],8,0,entry["employee_id"],database_path=workflow_db)
    assert result["validation"]["payroll_run_id"] == result["payroll_run"]["payroll_run_id"]
    assert result["validation"]["exceptions_by_category"].get("TIME_UNAPPROVED",0) == 0
    with connect(workflow_db) as db:
        assert db.execute("SELECT regular_hours FROM time_entries WHERE time_entry_id=?",(entry["time_entry_id"],)).fetchone()[0] == original_hours
        assert db.execute("SELECT COUNT(*) FROM payroll_runs WHERE pay_period_id=?",(entry["pay_period_id"],)).fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM approval_history WHERE payroll_input_id=? AND action_type='correction_revalidated'",(item,)).fetchone()[0] == 1
    with pytest.raises(PermissionError):
        review_payroll_input(item,"employee","Employee","Approved","self approve",workflow_db)


def test_run_approval_requires_manager_or_hr_and_keeps_legacy_flow(workflow_db):
    period = _clean_period(workflow_db)
    run = process_payroll_period(period,workflow_db)
    validate_payroll_run(run["payroll_run_id"],workflow_db)
    with pytest.raises(PermissionError):
        approve_payroll_run(run["payroll_run_id"],"ops","IT/Operations Partner",reviewer_role="IT/Operations Partner")
    assert approve_payroll_run(run["payroll_run_id"],"hr",workflow_db,reviewer_role="HR Partner")["status"] == "approved"
    with connect(workflow_db) as db:
        assert db.execute("SELECT COUNT(*) FROM approval_history WHERE payroll_run_id=? AND new_status='approved'",(run["payroll_run_id"],)).fetchone()[0] > 0

