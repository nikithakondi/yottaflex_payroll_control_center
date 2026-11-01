"""Calculate payroll components from source records and compare run results."""
import json
from decimal import Decimal, ROUND_HALF_UP

from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect

CENT = Decimal("0.01")


def money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def source_components(db, employee_id, pay_period_id):
    """Aggregate effective approved time, eligible leave and adjustments."""
    time = db.execute(
        "SELECT COALESCE(SUM(t.regular_hours),0) AS regular_hours, COALESCE(SUM(t.overtime_hours),0) AS overtime_hours "
        "FROM time_entries t WHERE t.employee_id=? AND t.pay_period_id=? AND t.approval_status='approved' "
        "AND t.status='approved' AND NOT EXISTS (SELECT 1 FROM time_entries c "
        "WHERE c.supersedes_time_entry_id=t.time_entry_id AND c.approval_status='approved' AND c.status='approved')",
        (employee_id, pay_period_id),
    ).fetchone()
    paid_leave = db.execute(
        "SELECT COALESCE(SUM(hours),0) FROM leave_records WHERE employee_id=? AND pay_period_id=? "
        "AND leave_type='paid' AND status='approved' AND NOT EXISTS (SELECT 1 FROM leave_records c WHERE c.supersedes_leave_id=leave_records.leave_id AND c.status='approved')", (employee_id,pay_period_id),
    ).fetchone()[0]
    allowances = db.execute(
        "SELECT COALESCE(SUM(a.amount),0) FROM allowances a WHERE a.employee_id=? AND a.pay_period_id=? AND a.eligible=1 AND NOT EXISTS (SELECT 1 FROM allowances c WHERE c.supersedes_allowance_id=a.allowance_id)",
        (employee_id,pay_period_id),
    ).fetchone()[0]
    deductions = db.execute(
        "SELECT COALESCE(SUM(d.amount),0) FROM deductions d WHERE d.employee_id=? AND d.pay_period_id=? AND d.eligible=1 "
        "AND NOT EXISTS (SELECT 1 FROM deductions c WHERE c.supersedes_deduction_id=d.deduction_id)",
        (employee_id,pay_period_id),
    ).fetchone()[0]
    return {
        "regular_hours": float(time["regular_hours"]),
        "overtime_hours": float(time["overtime_hours"]),
        "paid_leave_hours": float(paid_leave),
        "allowance_total": money(allowances),
        "deduction_total": money(deductions),
    }


def calculate_pay_components(source, hourly_rate, overtime_multiplier=1.5):
    """Calculate expected pay exclusively from source aggregates and pay rate."""
    rate = Decimal(str(hourly_rate or 0))
    regular_pay = money((Decimal(str(source["regular_hours"])) + Decimal(str(source["paid_leave_hours"]))) * rate)
    overtime_pay = money(Decimal(str(source["overtime_hours"])) * rate * Decimal(str(overtime_multiplier)))
    gross_pay = money(regular_pay + source["allowance_total"] + overtime_pay)
    net_pay = money(gross_pay - source["deduction_total"])
    return {
        "regular_hours": source["regular_hours"],
        "overtime_hours": source["overtime_hours"],
        "regular_pay": regular_pay,
        "overtime_pay": overtime_pay,
        "allowance_total": source["allowance_total"],
        "deduction_total": source["deduction_total"],
        "gross_pay": gross_pay,
        "net_pay": net_pay,
    }


def reconcile_payroll_run(database_path=DATABASE_PATH, payroll_run_id=None):
    """Return calculation and total-reconciliation findings for a run."""
    with connect(database_path) as db:
        if payroll_run_id is None:
            runs = [r[0] for r in db.execute("SELECT payroll_run_id FROM payroll_runs ORDER BY payroll_run_id")]
        else:
            runs = [payroll_run_id]
        findings = []
        for run_id in runs:
            run_finding_start = len(findings)
            run = db.execute(
                "SELECT r.payroll_run_id,r.run_number,p.pay_period_id,p.pay_group_id,g.overtime_multiplier "
                "FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) JOIN pay_groups g USING(pay_group_id) "
                "WHERE r.payroll_run_id=?", (run_id,),
            ).fetchone()
            if run is None:
                continue
            results = list(db.execute(
                "SELECT pr.*,e.employee_number,e.hourly_rate FROM payroll_results pr "
                "JOIN employees e USING(employee_id) WHERE pr.payroll_run_id=? ORDER BY e.employee_number", (run_id,),
            ))
            result_employees = {row["employee_id"] for row in results}
            expected_employees = list(db.execute(
                "SELECT employee_id,employee_number FROM employees WHERE pay_group_id=? AND employment_status='active'",
                (run["pay_group_id"],),
            ))
            for employee in expected_employees:
                if employee["employee_id"] not in result_employees:
                    findings.append(_finding("INCORRECT_PAYROLL_CALCULATION", "critical", employee["employee_id"], employee["employee_number"], run["pay_period_id"], None,
                                             "payroll_results", f"missing:{employee['employee_number']}", "one result row", "missing"))
                source=source_components(db,employee["employee_id"],run["pay_period_id"])
                source_fields={"regular_hours":source["regular_hours"],"overtime_hours":source["overtime_hours"],
                               "paid_leave_hours":source["paid_leave_hours"],"allowance_total":float(source["allowance_total"]),
                               "deduction_total":float(source["deduction_total"])}
                input_row=db.execute(
                    "SELECT * FROM payroll_run_inputs WHERE payroll_run_id=? AND employee_id=?",
                    (run_id,employee["employee_id"]),
                ).fetchone()
                if input_row is None:
                    findings.append(_finding("INCORRECT_PAYROLL_CALCULATION","critical",employee["employee_id"],employee["employee_number"],run["pay_period_id"],None,
                                             "payroll_run_inputs",f"missing:{employee['employee_number']}","one source-derived input snapshot","missing"))
                else:
                    input_differences={field:{"expected":value,"actual":float(input_row[field])}
                                       for field,value in source_fields.items() if abs(value-float(input_row[field]))>0.005}
                    if input_differences:
                        findings.append(_finding("INCORRECT_PAYROLL_CALCULATION","critical",employee["employee_id"],employee["employee_number"],run["pay_period_id"],None,
                                                 "payroll_run_inputs",str(input_row["payroll_run_input_id"]),
                                                 {key:value["expected"] for key,value in input_differences.items()},
                                                 {key:value["actual"] for key,value in input_differences.items()},input_differences))
                if run["run_number"] == 1:
                    base_input=db.execute("SELECT * FROM payroll_inputs WHERE employee_id=? AND pay_period_id=?",
                                          (employee["employee_id"],run["pay_period_id"])).fetchone()
                    if base_input is None:
                        findings.append(_finding("INCORRECT_PAYROLL_CALCULATION","critical",employee["employee_id"],employee["employee_number"],run["pay_period_id"],None,
                                                 "payroll_inputs",f"missing:{employee['employee_number']}","one source-derived input row","missing"))
                    else:
                        base_differences={field:{"expected":value,"actual":float(base_input[field])}
                                          for field,value in source_fields.items() if abs(value-float(base_input[field]))>0.005}
                        if base_differences:
                            findings.append(_finding("INCORRECT_PAYROLL_CALCULATION","critical",employee["employee_id"],employee["employee_number"],run["pay_period_id"],None,
                                                     "payroll_inputs",str(base_input["payroll_input_code"]),
                                                     {key:value["expected"] for key,value in base_differences.items()},
                                                     {key:value["actual"] for key,value in base_differences.items()},base_differences))

            expected_gross_total = Decimal("0.00")
            expected_net_total = Decimal("0.00")
            for result in results:
                source = source_components(db,result["employee_id"],run["pay_period_id"])
                expected = calculate_pay_components(source,result["hourly_rate"],run["overtime_multiplier"])
                expected_gross_total += expected["gross_pay"]
                expected_net_total += expected["net_pay"]
                component_fields = ("regular_hours","overtime_hours","regular_pay","overtime_pay","allowance_total","deduction_total")
                component_differences = {
                    field:{"expected":float(expected[field]),"actual":float(result[field])}
                    for field in component_fields
                    if abs(float(expected[field])-float(result[field])) > 0.005
                }
                if component_differences:
                    findings.append(_finding(
                        "INCORRECT_PAYROLL_CALCULATION","critical",result["employee_id"],result["employee_number"],
                        run["pay_period_id"],None,"payroll_results",str(result["payroll_result_id"]),
                        {key:value["expected"] for key,value in component_differences.items()},
                        {key:value["actual"] for key,value in component_differences.items()},component_differences,
                    ))

                expected_gross = money(expected["regular_pay"]+expected["overtime_pay"]+expected["allowance_total"])
                expected_net = money(expected_gross-expected["deduction_total"])
                actual_gross = money(result["gross_pay"])
                actual_net = money(result["net_pay"])
                differences = {}
                if actual_gross != expected_gross:
                    differences["gross_pay"] = {"expected":float(expected_gross),"actual":float(actual_gross)}
                if actual_net != expected_net:
                    differences["net_pay"] = {"expected":float(expected_net),"actual":float(actual_net)}
                if differences:
                    findings.append(_finding(
                        "PAYROLL_RECONCILIATION","critical",result["employee_id"],result["employee_number"],
                        run["pay_period_id"],None,"payroll_results",str(result["payroll_result_id"]),
                        {key:value["expected"] for key,value in differences.items()},
                        {key:value["actual"] for key,value in differences.items()},differences,
                    ))
            run_findings = findings[run_finding_start:]
            mismatching_employees = {row["employee_reference"] for row in run_findings if row.get("employee_reference")}
            actual_gross_total = money(sum((money(row["gross_pay"]) for row in results), Decimal("0.00")))
            actual_net_total = money(sum((money(row["net_pay"]) for row in results), Decimal("0.00")))
            checked_records = len(expected_employees)
            reconciliation_summary = {
                "payroll_run_id": run_id,
                "records_checked": checked_records,
                "matching_records": max(checked_records - len(mismatching_employees), 0),
                "mismatching_records": len(mismatching_employees),
                "expected_gross_pay": float(money(expected_gross_total)),
                "actual_gross_pay": float(actual_gross_total),
                "gross_difference": float(money(actual_gross_total - money(expected_gross_total))),
                "expected_net_pay": float(money(expected_net_total)),
                "actual_net_pay": float(actual_net_total),
                "net_difference": float(money(actual_net_total - money(expected_net_total))),
                "findings": run_findings,
            }
            db.execute(
                "INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) "
                "VALUES ('payroll_run',?,'reconciliation_completed','reconciliation_service',NULL,?)",
                (str(run_id), json.dumps(reconciliation_summary, sort_keys=True, default=str)),
            )
        return findings


def _finding(rule_code,severity,employee_id,employee_reference,pay_period_id,pay_period_reference,entity_type,entity_id,expected,actual,details=None):
    return {"rule_code":rule_code,"severity":severity,"employee_id":employee_id,
            "employee_reference":employee_reference,"pay_period_id":pay_period_id,
            "pay_period_reference":pay_period_reference,"entity_type":entity_type,"entity_id":entity_id,
            "expected_value":expected,"actual_value":actual,"details":details or {},
            "message":rule_code.replace('_',' ').title()}
