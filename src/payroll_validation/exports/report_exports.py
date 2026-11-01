"""Downloadable validation and reconciliation reports."""
import csv
import io
import json

import pandas as pd

from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.reconciliation_service import (
    calculate_pay_components,
    reconcile_payroll_run,
    source_components,
)


def validation_report_rows(payroll_run_id, database_path=DATABASE_PATH):
    """Return persisted validation exceptions for one payroll run."""
    with connect(database_path) as db:
        return [dict(row) for row in db.execute(
            "SELECT exception_code,employee_reference AS employee_id,pay_period_reference AS pay_period_id,"
            "rule_code AS validation_rule,severity,status,workflow_status AS validation_status,message,"
            "expected_value,actual_value,detected_at,entity_type,entity_id "
            "FROM exceptions WHERE payroll_run_id=? ORDER BY exception_id",
            (payroll_run_id,),
        )]


def reconciliation_report_rows(payroll_run_id, database_path=DATABASE_PATH):
    """Return expected/actual totals and matching state per employee."""
    findings = reconcile_payroll_run(database_path, payroll_run_id)
    findings_by_employee = {}
    for finding in findings:
        findings_by_employee.setdefault(finding.get("employee_reference"), []).append(finding["rule_code"])

    with connect(database_path) as db:
        run = db.execute(
            "SELECT r.payroll_run_id,p.pay_period_code,p.pay_period_id,g.overtime_multiplier "
            "FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) "
            "JOIN pay_groups g USING(pay_group_id) WHERE r.payroll_run_id=?",
            (payroll_run_id,),
        ).fetchone()
        if run is None:
            raise KeyError(f"Unknown payroll_run_id {payroll_run_id}")
        results = list(db.execute(
            "SELECT pr.*,e.employee_number,e.department,e.hourly_rate FROM payroll_results pr "
            "JOIN employees e USING(employee_id) WHERE pr.payroll_run_id=? ORDER BY e.employee_number",
            (payroll_run_id,),
        ))
        rows = []
        for result in results:
            source = source_components(db, result["employee_id"], run["pay_period_id"])
            expected = calculate_pay_components(source, result["hourly_rate"], run["overtime_multiplier"])
            expected_gross = float(expected["gross_pay"])
            expected_net = float(expected["net_pay"])
            gross_difference = round(float(result["gross_pay"]) - expected_gross, 2)
            net_difference = round(float(result["net_pay"]) - expected_net, 2)
            rule_codes = sorted(set(findings_by_employee.get(result["employee_number"], [])))
            rows.append({
                "payroll_run_id": payroll_run_id,
                "pay_period_id": run["pay_period_code"],
                "employee_id": result["employee_number"],
                "department": result["department"],
                "expected_gross_pay": expected_gross,
                "actual_gross_pay": float(result["gross_pay"]),
                "gross_difference": gross_difference,
                "expected_net_pay": expected_net,
                "actual_net_pay": float(result["net_pay"]),
                "net_difference": net_difference,
                "status": "Mismatch" if gross_difference or net_difference or rule_codes else "Match",
                "validation_rules": ", ".join(rule_codes),
            })
        return rows


def report_bytes(rows, output_format="csv", sheet_name="Report"):
    """Serialize report rows for Streamlit or other download clients."""
    output_format = str(output_format).lower()
    if output_format not in {"csv", "xlsx", "json"}:
        raise ValueError("Report format must be csv, xlsx, or json")
    frame = pd.DataFrame(rows)
    if output_format == "json":
        return json.dumps(rows, indent=2, default=str).encode("utf-8")
    if output_format == "csv":
        if not rows:
            return b""
        stream = io.StringIO(newline="")
        frame.to_csv(stream, index=False, quoting=csv.QUOTE_MINIMAL)
        return stream.getvalue().encode("utf-8")
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet_name[:31] or "Report")
    return stream.getvalue()
