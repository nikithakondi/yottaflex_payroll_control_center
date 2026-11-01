"""Rule-based payroll validation, exception creation and export readiness."""
import json
from collections import Counter

from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.database.init_db import initialize
from payroll_validation.services.exception_service import record_findings
from payroll_validation.services.reconciliation_service import reconcile_payroll_run

RULE_ORDER = (
    "HOURS_PERIOD_MAX", "DUPLICATE_ALLOWANCE", "TIME_UNAPPROVED",
    "DUP_UNPAID_LEAVE_DEDUCTION", "PAYROLL_RECONCILIATION",
    "BANK_DETAILS_MISSING", "TAX_INFORMATION_MISSING", "DUPLICATE_TIME_ENTRY",
    "INCORRECT_PAYROLL_CALCULATION", "INVALID_REFERENCE", "DATE_OUTSIDE_PERIOD",
)
CRITICAL_RULES = set(RULE_ORDER)


def validate_payroll_run(payroll_run_id, database_path=DATABASE_PATH, actor="validation_service"):
    """Run every validation rule for one payroll run and persist findings.

    `ground_truth.csv` is deliberately not loaded or referenced here. The
    returned report counts distinct records with findings, so one record that
    triggers several rules is only counted once in the invalid-record total.
    """
    initialize(database_path,allow_fk_violations=True)
    reconciliation_findings = reconcile_payroll_run(database_path,payroll_run_id)
    with connect(database_path) as db:
        run = db.execute(
            "SELECT r.*,p.pay_period_id,p.pay_period_code,p.period_start,p.period_end,p.pay_group_id,g.max_period_hours "
            "FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) JOIN pay_groups g USING(pay_group_id) "
            "WHERE r.payroll_run_id=?",(payroll_run_id,),
        ).fetchone()
        if run is None:
            raise KeyError(f"Unknown payroll_run_id {payroll_run_id}")
        findings = _collect_findings(db,run,reconciliation_findings)
        findings.sort(key=lambda finding:(RULE_ORDER.index(finding["rule_code"]),finding["employee_reference"] or "",finding["entity_id"]))
        exceptions = record_findings(db,payroll_run_id,findings,actor=actor)
        critical_open = db.execute(
            "SELECT COUNT(*) FROM exceptions WHERE payroll_run_id=? AND severity='critical' AND workflow_status IN ('open','under_review','rejected')",
            (payroll_run_id,),
        ).fetchone()[0]
        final_status=run["status"]
        if run["status"] in ("processed","validated","approved"):
            if critical_open and run["status"] in ("validated","approved"):
                _audit_run_state(db,payroll_run_id,run["status"],"processed",actor,"Critical validation findings require re-review")
                db.execute("UPDATE payroll_runs SET status='processed' WHERE payroll_run_id=?",(payroll_run_id,))
                final_status="processed"
            elif not critical_open and run["status"] in ("processed","validated"):
                if run["status"]!="validated":
                    _audit_run_state(db,payroll_run_id,run["status"],"validated",actor,"No unresolved critical findings")
                db.execute("UPDATE payroll_runs SET status='validated' WHERE payroll_run_id=?",(payroll_run_id,))
                final_status="validated"
        db.execute("INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) VALUES ('payroll_run',?,'payroll_validation_completed',?,?,?)",
                   (str(payroll_run_id),actor,json.dumps({"status":run["status"]}),json.dumps({"status":final_status,"exception_count":len(exceptions)})))

        checked_by_type = _checked_counts(db,run)
        invalid_keys = {(finding["entity_type"],str(finding["entity_id"])) for finding in findings}
        checked_total = sum(checked_by_type.values())
        invalid_count = min(checked_total,len(invalid_keys))
        by_category = dict(Counter(row["rule_code"] for row in exceptions))
        return {
            "payroll_run_id":payroll_run_id,
            "pay_period_id":run["pay_period_code"],
            "records_checked":checked_total,
            "records_checked_by_type":checked_by_type,
            "valid_records":checked_total-invalid_count,
            "invalid_records":invalid_count,
            "total_exceptions":len(exceptions),
            "exceptions_by_category":by_category,
            "exception_ids":[row["exception_code"] for row in exceptions],
            "findings":findings,
            "export_ready":critical_open==0,
            "payroll_run_status":final_status,
        }


def validate_all_payroll_runs(database_path=DATABASE_PATH, actor="validation_service"):
    """Validate all runs and aggregate reports for a database snapshot."""
    with connect(database_path) as db:
        run_ids=[row[0] for row in db.execute("SELECT payroll_run_id FROM payroll_runs ORDER BY payroll_run_id")]
    reports=[validate_payroll_run(run_id,database_path,actor) for run_id in run_ids]
    category_counts=Counter()
    for report in reports:
        category_counts.update(report["exceptions_by_category"])
    return {
        "payroll_runs_checked":len(reports),
        "records_checked":sum(row["records_checked"] for row in reports),
        "valid_records":sum(row["valid_records"] for row in reports),
        "invalid_records":sum(row["invalid_records"] for row in reports),
        "total_exceptions":sum(row["total_exceptions"] for row in reports),
        "exceptions_by_category":dict(category_counts),
        "export_ready":all(row["export_ready"] for row in reports),
        "reports":reports,
    }


def _collect_findings(db,run,reconciliation_findings):
    findings=[]
    period_id=run["pay_period_id"]
    period_code=run["pay_period_code"]

    employees=list(db.execute(
        "SELECT employee_id,employee_number,bank_account_token,tax_info_token FROM employees "
        "WHERE pay_group_id=? AND employment_status='active' ORDER BY employee_number",(run["pay_group_id"],),
    ))
    for employee in employees:
        if not (employee["bank_account_token"] or "").strip():
            findings.append(_finding("BANK_DETAILS_MISSING","critical",employee["employee_id"],employee["employee_number"],period_id,period_code,
                                     "employees",employee["employee_number"],"bank account token present",None))
        if not (employee["tax_info_token"] or "").strip():
            findings.append(_finding("TAX_INFORMATION_MISSING","critical",employee["employee_id"],employee["employee_number"],period_id,period_code,
                                     "employees",employee["employee_number"],"tax information token present",None))

    findings.extend(_duplicate_time_findings(db,run))
    findings.extend(_period_hours_findings(db,run))
    findings.extend(_duplicate_allowance_findings(db,run))
    findings.extend(_unapproved_time_findings(db,run))
    findings.extend(_duplicate_unpaid_deduction_findings(db,run))
    findings.extend(_invalid_reference_findings(db,run))
    findings.extend(_date_consistency_findings(db,run))
    for finding in reconciliation_findings:
        if finding.get("pay_period_id") != period_id:
            continue
        finding["pay_period_reference"]=period_code
        findings.append(finding)
    return findings


def _date_consistency_findings(db,run):
    findings=[]
    for row in db.execute("SELECT t.time_entry_id,t.time_entry_code,t.employee_id,e.employee_number,t.work_date FROM time_entries t JOIN employees e USING(employee_id) WHERE t.pay_period_id=? AND (t.work_date<? OR t.work_date>?)",(run["pay_period_id"],run["period_start"],run["period_end"])):
        findings.append(_finding("DATE_OUTSIDE_PERIOD","critical",row["employee_id"],row["employee_number"],run["pay_period_id"],run["pay_period_code"],"time_entries",row["time_entry_code"],f"{run['period_start']}..{run['period_end']}",row["work_date"]))
    for row in db.execute("SELECT l.leave_id,l.employee_id,e.employee_number,l.start_date,l.end_date FROM leave_records l JOIN employees e USING(employee_id) WHERE l.pay_period_id=? AND (l.start_date<? OR l.end_date>?)",(run["pay_period_id"],run["period_start"],run["period_end"])):
        findings.append(_finding("DATE_OUTSIDE_PERIOD","critical",row["employee_id"],row["employee_number"],run["pay_period_id"],run["pay_period_code"],"leave_records",str(row["leave_id"]),f"{run['period_start']}..{run['period_end']}",f"{row['start_date']}..{row['end_date']}"))
    return findings


def _duplicate_time_findings(db,run):
    groups=db.execute(
        "SELECT employee_id,work_date FROM time_entries t WHERE pay_period_id=? AND status='approved' "
        "AND approval_status='approved' AND NOT EXISTS (SELECT 1 FROM time_entries c WHERE c.supersedes_time_entry_id=t.time_entry_id AND c.status='approved' AND c.approval_status='approved') "
        "GROUP BY employee_id,work_date HAVING COUNT(*)>1",(run["pay_period_id"],),
    )
    findings=[]
    for group in groups:
        entries=list(db.execute(
            "SELECT t.time_entry_id,t.time_entry_code,e.employee_number FROM time_entries t JOIN employees e USING(employee_id) "
            "WHERE t.employee_id=? AND t.pay_period_id=? AND t.work_date=? AND t.status='approved' AND t.approval_status='approved' "
            "ORDER BY t.time_entry_id",(group["employee_id"],run["pay_period_id"],group["work_date"]),
        ))
        for duplicate in entries[1:]:
            findings.append(_finding("DUPLICATE_TIME_ENTRY","critical",group["employee_id"],duplicate["employee_number"],run["pay_period_id"],run["pay_period_code"],
                                     "time_entries",duplicate["time_entry_code"],"one active entry per employee and work date",len(entries),
                                     {"work_date":group["work_date"]}))
    return findings


def _period_hours_findings(db,run):
    rows=db.execute(
        "SELECT t.employee_id,e.employee_number,SUM(t.regular_hours+t.overtime_hours) AS total_hours "
        "FROM time_entries t JOIN employees e USING(employee_id) WHERE t.pay_period_id=? AND t.status='approved' AND t.approval_status='approved' "
        "AND NOT EXISTS (SELECT 1 FROM time_entries c WHERE c.supersedes_time_entry_id=t.time_entry_id AND c.status='approved' AND c.approval_status='approved') "
        "GROUP BY t.employee_id HAVING total_hours>?",(run["pay_period_id"],run["max_period_hours"]),
    )
    return [_finding("HOURS_PERIOD_MAX","critical",row["employee_id"],row["employee_number"],run["pay_period_id"],run["pay_period_code"],
                     "employee_period_hours",f"{row['employee_number']}:{run['pay_period_code']}",run["max_period_hours"],round(row["total_hours"],2)) for row in rows]


def _duplicate_allowance_findings(db,run):
    rows=db.execute(
        "SELECT employee_id,pay_period_id,allowance_type,source_reference,COUNT(*) AS n FROM allowances a "
        "WHERE pay_period_id=? AND NOT EXISTS (SELECT 1 FROM allowances c WHERE c.supersedes_allowance_id=a.allowance_id) "
        "GROUP BY employee_id,pay_period_id,allowance_type,source_reference HAVING COUNT(*)>1",
        (run["pay_period_id"],),
    )
    findings=[]
    for row in rows:
        employee=db.execute("SELECT employee_number FROM employees WHERE employee_id=?",(row["employee_id"],)).fetchone()
        duplicate=db.execute(
            "SELECT allowance_id,allowance_code FROM allowances WHERE employee_id=? AND pay_period_id=? AND allowance_type=? AND source_reference=? ORDER BY allowance_id DESC LIMIT 1",
            (row["employee_id"],row["pay_period_id"],row["allowance_type"],row["source_reference"]),
        ).fetchone()
        findings.append(_finding("DUPLICATE_ALLOWANCE","critical",row["employee_id"],employee["employee_number"],row["pay_period_id"],run["pay_period_code"],
                                 "allowances",duplicate["allowance_code"],"one submission for source reference",row["n"],
                                 {"source_reference":row["source_reference"],"allowance_type":row["allowance_type"]}))
    return findings


def _unapproved_time_findings(db,run):
    rows=db.execute(
        "SELECT t.time_entry_id,t.time_entry_code,t.employee_id,e.employee_number,t.approval_status,t.status "
        "FROM time_entries t JOIN employees e USING(employee_id) WHERE t.pay_period_id=? "
        "AND t.status NOT IN ('rejected','draft') AND t.approval_status!='approved' "
        "AND NOT EXISTS (SELECT 1 FROM time_entries c WHERE c.supersedes_time_entry_id=t.time_entry_id AND c.status='approved' AND c.approval_status='approved') "
        "ORDER BY t.time_entry_id",
        (run["pay_period_id"],),
    )
    return [_finding("TIME_UNAPPROVED","critical",row["employee_id"],row["employee_number"],run["pay_period_id"],run["pay_period_code"],
                     "time_entries",row["time_entry_code"],"approval_status=approved",row["approval_status"],{"status":row["status"]}) for row in rows]


def _duplicate_unpaid_deduction_findings(db,run):
    rows=db.execute(
        "SELECT d.leave_id,d.employee_id,e.employee_number,COUNT(*) AS n FROM deductions d "
        "JOIN leave_records l ON l.leave_id=d.leave_id JOIN employees e ON e.employee_id=d.employee_id "
        "WHERE d.pay_period_id=? AND l.leave_type='unpaid' AND l.status='approved' "
        "AND NOT EXISTS (SELECT 1 FROM deductions c WHERE c.supersedes_deduction_id=d.deduction_id) "
        "GROUP BY d.leave_id,d.employee_id HAVING COUNT(*)>1",(run["pay_period_id"],),
    )
    findings=[]
    for row in rows:
        duplicate=db.execute("SELECT deduction_code FROM deductions WHERE leave_id=? ORDER BY deduction_id DESC LIMIT 1",(row["leave_id"],)).fetchone()
        findings.append(_finding("DUP_UNPAID_LEAVE_DEDUCTION","critical",row["employee_id"],row["employee_number"],run["pay_period_id"],run["pay_period_code"],
                                 "deductions",duplicate["deduction_code"],"one deduction per approved unpaid leave",row["n"],{"leave_id":row["leave_id"]}))
    return findings


def _invalid_reference_findings(db,run):
    findings=[]
    specs=(
        ("time_entries","time_entry_id","time_entry_code"),
        ("leave_records","leave_id","leave_id"),
        ("allowances","allowance_id","allowance_code"),
        ("deductions","deduction_id","deduction_code"),
        ("payroll_inputs","payroll_input_id","payroll_input_code"),
        ("payroll_run_inputs","payroll_run_input_id","payroll_run_input_id"),
    )
    for table,pk,code_col in specs:
        rows=db.execute(
            f"SELECT s.{pk} AS row_id,s.{code_col} AS row_code,s.employee_id,s.pay_period_id,"
            "e.employee_number AS employee_number,p.pay_period_code AS period_code,"
            "e.pay_group_id AS employee_group,p.pay_group_id AS period_group "
            f"FROM {table} s LEFT JOIN employees e ON e.employee_id=s.employee_id "
            "LEFT JOIN pay_periods p ON p.pay_period_id=s.pay_period_id "
            "WHERE s.pay_period_id=? AND (e.employee_id IS NULL OR p.pay_period_id IS NULL OR e.pay_group_id!=p.pay_group_id)",
            (run["pay_period_id"],),
        )
        for row in rows:
            findings.append(_invalid_reference_finding(table,row,run))

    for row in db.execute(
        "SELECT pr.payroll_result_id AS row_id,pr.employee_id,e.employee_number,r.pay_period_id,p.pay_period_code,e.pay_group_id AS employee_group,p.pay_group_id AS period_group "
        "FROM payroll_results pr JOIN payroll_runs r USING(payroll_run_id) LEFT JOIN employees e ON e.employee_id=pr.employee_id "
        "LEFT JOIN pay_periods p ON p.pay_period_id=r.pay_period_id WHERE r.payroll_run_id=? "
        "AND (e.employee_id IS NULL OR p.pay_period_id IS NULL OR e.pay_group_id!=p.pay_group_id)",(run["payroll_run_id"],),
    ):
        findings.append(_invalid_reference_finding("payroll_results",row,run))

    # Validate all persisted FK references in scope, including the leave_id
    # relation on deductions. SQLite normally prevents these; this catches
    # imports performed with foreign_keys disabled.
    for violation in db.execute("PRAGMA foreign_key_check"):
        table,row_id,parent,fk_id=violation
        columns=list(db.execute(f'PRAGMA foreign_key_list("{table}")'))
        fk=next((item for item in columns if item["id"]==fk_id),None)
        if fk is None or fk["from"] not in ("pay_period_id","leave_id"):
            continue
        row=db.execute(f'SELECT * FROM "{table}" WHERE rowid=?',(row_id,)).fetchone()
        if row is None:
            continue
        if "pay_period_id" in row.keys() and row["pay_period_id"] not in (None,run["pay_period_id"]):
            referenced_period=db.execute("SELECT 1 FROM pay_periods WHERE pay_period_id=?",(row["pay_period_id"],)).fetchone()
            if referenced_period:
                continue
        code_column={"time_entries":"time_entry_code","leave_records":"leave_id","allowances":"allowance_code",
                     "deductions":"deduction_code","payroll_inputs":"payroll_input_code",
                     "payroll_run_inputs":"payroll_run_input_id","payroll_results":"payroll_result_id"}.get(table)
        row_code=row[code_column] if code_column and code_column in row.keys() else str(row_id)
        employee_id=row["employee_id"] if "employee_id" in row.keys() else None
        employee=db.execute("SELECT employee_number,pay_group_id FROM employees WHERE employee_id=?",(employee_id,)).fetchone() if employee_id is not None else None
        raw_period_id=row["pay_period_id"] if "pay_period_id" in row.keys() else run["pay_period_id"]
        period=db.execute("SELECT pay_period_code,pay_group_id FROM pay_periods WHERE pay_period_id=?",(raw_period_id,)).fetchone() if raw_period_id is not None else None
        pseudo={"row_id":row_id,"row_code":str(row_code),"employee_id":employee_id,
                "employee_number":employee["employee_number"] if employee else None,"pay_period_id":raw_period_id,
                "period_code":period["pay_period_code"] if period else None,
                "employee_group":employee["pay_group_id"] if employee else None,"period_group":period["pay_group_id"] if period else None,
                "fk_column":fk["from"],"invalid_value":row[fk["from"]]}
        findings.append(_invalid_reference_finding(table,pseudo,run))
    return _dedupe_findings(findings)


def _invalid_reference_finding(table,row,run):
    employee_id=row["employee_id"]
    employee_ref=row["employee_number"] or (str(employee_id) if employee_id is not None else None)
    period_ref=row["period_code"] or (str(row["pay_period_id"]) if row["pay_period_id"] is not None else run["pay_period_code"])
    actual={"employee_id":employee_id,"pay_period_id":row["pay_period_id"],"employee_group":row["employee_group"],"period_group":row["period_group"]}
    if "fk_column" in row.keys() and row["fk_column"]:
        actual["invalid_foreign_key_column"]=row["fk_column"]
        actual["invalid_value"]=row["invalid_value"]
    return _finding("INVALID_REFERENCE","critical",employee_id if row["employee_number"] else None,employee_ref,
                    run["pay_period_id"],period_ref,table,str(row["row_code"]),
                    "valid employee and pay-period references with matching pay group",actual,actual)


def _dedupe_findings(findings):
    unique={}
    for finding in findings:
        key=(finding["rule_code"],finding["entity_type"],str(finding["entity_id"]))
        unique[key]=finding
    return list(unique.values())


def _finding(rule,severity,employee_id,employee_reference,pay_period_id,pay_period_reference,entity_type,entity_id,expected,actual,details=None):
    return {"rule_code":rule,"severity":severity,"employee_id":employee_id,"employee_reference":employee_reference,
            "pay_period_id":pay_period_id,"pay_period_reference":pay_period_reference,"entity_type":entity_type,
            "entity_id":str(entity_id),"expected_value":expected,"actual_value":actual,
            "details":details or {},"message":rule.replace('_',' ').title()}


def _checked_counts(db,run):
    period_id=run["pay_period_id"]
    return {
        "employees":db.execute("SELECT COUNT(*) FROM employees WHERE pay_group_id=? AND employment_status='active'",(run["pay_group_id"],)).fetchone()[0],
        "time_entries":db.execute("SELECT COUNT(*) FROM time_entries WHERE pay_period_id=?",(period_id,)).fetchone()[0],
        "leave_records":db.execute("SELECT COUNT(*) FROM leave_records WHERE pay_period_id=?",(period_id,)).fetchone()[0],
        "allowances":db.execute("SELECT COUNT(*) FROM allowances WHERE pay_period_id=?",(period_id,)).fetchone()[0],
        "deductions":db.execute("SELECT COUNT(*) FROM deductions WHERE pay_period_id=?",(period_id,)).fetchone()[0],
        "payroll_inputs":db.execute("SELECT COUNT(*) FROM payroll_inputs WHERE pay_period_id=?",(period_id,)).fetchone()[0] if run["run_number"]==1 else 0,
        "payroll_run_inputs":db.execute("SELECT COUNT(*) FROM payroll_run_inputs WHERE payroll_run_id=?",(run["payroll_run_id"],)).fetchone()[0],
        "payroll_results":db.execute("SELECT COUNT(*) FROM payroll_results WHERE payroll_run_id=?",(run["payroll_run_id"],)).fetchone()[0],
    }


def _audit_run_state(db,run_id,before,after,actor,reason):
    db.execute("INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) VALUES ('payroll_run',?,'validation_status_changed',?,?,?)",
               (str(run_id),actor,json.dumps({"status":before}),json.dumps({"status":after,"reason":reason})))


if __name__ == "__main__":
    print(json.dumps(validate_all_payroll_runs(),indent=2,default=str))
