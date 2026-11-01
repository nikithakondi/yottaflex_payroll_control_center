import json
import shutil
from io import BytesIO

import pytest
from openpyxl import load_workbook

from payroll_validation.database.connection import connect
from payroll_validation.database.init_db import initialize
from payroll_validation.generators.generate_dataset import generate_dataset
from payroll_validation.approvals.approval_service import review_payroll_input, submit_source_correction
from payroll_validation.services.payroll_service import process_payroll_period, approve_payroll_run, export_payroll_run
from payroll_validation.validators.validation_service import validate_payroll_run, validate_all_payroll_runs
from payroll_validation.exports.report_exports import (
    reconciliation_report_rows, report_bytes, validation_report_rows,
)

@pytest.fixture
def db_copy(tmp_path):
    original=tmp_path/"source.db"
    generate_dataset("starter",database_path=original,output_dir=tmp_path/"source")
    working=tmp_path/"working.db"; shutil.copy2(original,working)
    return working

def _clean_source(db_path):
    with connect(db_path) as db:
        db.execute("DELETE FROM time_entries WHERE source IN ('anomaly_hours_over_max','anomaly_unapproved_time')")
        db.execute("DELETE FROM allowances WHERE submission_type='duplicate'")
        db.execute("DELETE FROM deductions WHERE submission_type='duplicate'")

def test_validation_rule_catalog_and_migrated_workflow_schema(db_copy):
    result=initialize(db_copy)
    assert result["table_count"] >= 19
    with connect(db_copy) as db:
        assert db.execute("SELECT COUNT(*) FROM validation_rules WHERE is_active=1").fetchone()[0] == 11
        assert db.execute("SELECT COUNT(*) FROM exceptions WHERE validation_rule_id IS NOT NULL").fetchone()[0] == 0
        assert not list(db.execute("PRAGMA foreign_key_check"))

def test_out_of_period_import_is_detected(db_copy):
    with connect(db_copy) as db:
        employee=db.execute("SELECT employee_id FROM employees ORDER BY employee_id LIMIT 1").fetchone()[0]
        db.execute("DROP TRIGGER trg_time_entry_date_insert")
        db.execute("INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type) VALUES (?,1,'2025-12-31','TIME-EMP-000001-2025-12-31',8,0,'broken_import','approved','approved','original')",(employee,))
    report=validate_payroll_run(1,db_copy)
    assert report["exceptions_by_category"]["DATE_OUTSIDE_PERIOD"]==1

@pytest.mark.parametrize("entity,table,pk,amount",[
    ("leave_record","leave_records","leave_id",None),
    ("allowance","allowances","allowance_id",125.0),
    ("deduction","deductions","deduction_id",75.0),
    ("time_entry","time_entries","time_entry_id",None),
])
def test_correction_types_append_and_create_revalidated_run(db_copy,entity,table,pk,amount):
    _clean_source(db_copy)
    with connect(db_copy) as db:
        source=db.execute(f"SELECT * FROM {table} WHERE "+("status='approved' AND " if entity=="time_entry" else "")+f"pay_period_id IN (SELECT pay_period_id FROM pay_periods) ORDER BY {pk} LIMIT 1").fetchone()
        assert source is not None
        period=source["pay_period_id"]
        item=db.execute("SELECT payroll_input_id,employee_id FROM payroll_inputs WHERE employee_id=? AND pay_period_id=?",(source["employee_id"],period)).fetchone()
        original=dict(source)
        run=process_payroll_period(period,db_copy)
    validate_payroll_run(run["payroll_run_id"],db_copy)
    review_payroll_input(item["payroll_input_id"],"manager","Manager","Correction Required","source correction requested",db_copy,run["payroll_run_id"])
    if entity=="time_entry": changes={"regular_hours":8.0,"overtime_hours":0.0}
    elif entity=="leave_record": changes={"hours":4.0,"status":"approved"}
    else: changes={"amount":amount}
    result=submit_source_correction(item["payroll_input_id"],entity,source[pk],changes,item["employee_id"],database_path=db_copy,comments="corrected",payroll_run_id=run["payroll_run_id"])
    assert result["payroll_run"]["payroll_run_id"] > run["payroll_run_id"]
    assert result["validation"]["payroll_run_status"]=="validated"
    with connect(db_copy) as db:
        after=db.execute(f"SELECT * FROM {table} WHERE {pk}=?",(source[pk],)).fetchone()
        assert dict(after)==original
        assert db.execute("SELECT COUNT(*) FROM approval_history WHERE payroll_input_id=? AND action_type='correction_revalidated'",(item["payroll_input_id"],)).fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM payroll_runs WHERE pay_period_id=?",(period,)).fetchone()[0]==3

def test_json_export_summary_and_duplicate_export_block(db_copy,tmp_path):
    _clean_source(db_copy)
    with connect(db_copy) as db: period=db.execute("SELECT pay_period_id FROM pay_periods WHERE pay_period_code='PP-2026-03'").fetchone()[0]
    run=process_payroll_period(period,db_copy)
    assert validate_payroll_run(run["payroll_run_id"],db_copy)["export_ready"]
    approve_payroll_run(run["payroll_run_id"],"hr-reviewer",db_copy,reviewer_role="HR Partner")
    output=tmp_path/"payroll.json"
    info=export_payroll_run(run["payroll_run_id"],output,db_copy,actor="pytest",output_format="json")
    payload=json.loads(output.read_text(encoding="utf-8"))
    assert info["format"]=="json" and info["record_count"]==100
    assert round(sum(row["gross_pay"] for row in payload),2)==info["summary"]["gross_pay"]
    with pytest.raises(ValueError,match="already been exported"):
        export_payroll_run(run["payroll_run_id"],tmp_path/"second.json",db_copy,output_format="json")

def test_excel_payroll_and_validation_reconciliation_report_exports(db_copy,tmp_path):
    anomaly_validation=validate_all_payroll_runs(db_copy)
    assert anomaly_validation["total_exceptions"]==5
    anomaly_rows=[row for run_report in anomaly_validation["reports"] for row in validation_report_rows(run_report["payroll_run_id"],db_copy)]
    assert len(anomaly_rows)==5
    anomaly_book=load_workbook(BytesIO(report_bytes(anomaly_rows,"xlsx","Validation")),read_only=True,data_only=True)
    assert anomaly_book.active.max_row==6

    _clean_source(db_copy)
    with connect(db_copy) as db:
        period=db.execute("SELECT pay_period_id FROM pay_periods WHERE pay_period_code='PP-2026-03'").fetchone()[0]
    run=process_payroll_period(period,db_copy)
    validation=validate_payroll_run(run["payroll_run_id"],db_copy)
    assert validation["export_ready"]
    approve_payroll_run(run["payroll_run_id"],"excel-reviewer",db_copy,reviewer_role="Approver")
    payroll_path=tmp_path/"approved-payroll.xlsx"
    exported=export_payroll_run(run["payroll_run_id"],payroll_path,db_copy,actor="pytest",output_format="xlsx")
    assert exported["format"]=="xlsx" and exported["record_count"]==100
    workbook=load_workbook(payroll_path,read_only=True,data_only=True)
    assert workbook.sheetnames==["Approved Payroll"]
    assert workbook.active.max_row==101
    assert "net_pay" in [cell.value for cell in next(workbook.active.iter_rows(min_row=1,max_row=1))]

    validation_rows=validation_report_rows(run["payroll_run_id"],db_copy)
    reconciliation_rows=reconciliation_report_rows(run["payroll_run_id"],db_copy)
    assert len(validation_rows)==0
    assert len(reconciliation_rows)==100
    assert {row["status"] for row in reconciliation_rows}=={"Match"}
    for rows,sheet in ((validation_rows,"Validation"),(reconciliation_rows,"Reconciliation")):
        payload=report_bytes(rows,"xlsx",sheet)
        report_book=load_workbook(BytesIO(payload),read_only=True,data_only=True)
        assert report_book.sheetnames==[sheet]
    assert b"employee_id" in report_bytes(reconciliation_rows,"csv")
