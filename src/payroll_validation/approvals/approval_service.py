"""Append-only employee payroll review decisions and correction workflow."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.roles import require_role

STATUS = {"pending", "approved", "rejected", "correction_required"}
REVIEWERS = {"Manager", "HR Partner"}

def review_payroll_input(payroll_input_id, reviewer_id, reviewer_role, new_status, comments=None,
                         database_path=DATABASE_PATH, payroll_run_id=None, exception_id=None):
    role = require_role(reviewer_role, REVIEWERS)
    status = str(new_status).strip().lower().replace(" ", "_")
    if status not in STATUS or status == "pending":
        raise ValueError("Review status must be Approved, Rejected, or Correction Required")
    with connect(database_path) as db:
        item = db.execute("SELECT * FROM payroll_inputs WHERE payroll_input_id=?", (payroll_input_id,)).fetchone()
        if item is None:
            raise KeyError(f"Unknown payroll_input_id {payroll_input_id}")
        if payroll_run_id is None:
            run = db.execute("SELECT payroll_run_id FROM payroll_runs WHERE pay_period_id=? ORDER BY run_number DESC LIMIT 1", (item["pay_period_id"],)).fetchone()
            if run is None: raise ValueError("Payroll input has no processed payroll run")
            payroll_run_id = run[0]
        exists = db.execute("SELECT 1 FROM payroll_run_inputs WHERE payroll_run_id=? AND employee_id=?", (payroll_run_id,item["employee_id"])).fetchone()
        if not exists: raise ValueError("Payroll input is not part of the selected payroll run")
    if status == "approved":
        from payroll_validation.validators.validation_service import validate_payroll_run
        report = validate_payroll_run(payroll_run_id, database_path, actor=reviewer_id)
        if not report["export_ready"]:
            raise ValueError("Approval blocked: invalid payroll or unresolved critical exception")
    with connect(database_path) as db:
        previous = db.execute("SELECT new_status FROM approval_history WHERE payroll_run_id=? AND payroll_input_id=? ORDER BY approval_id DESC LIMIT 1", (payroll_run_id,payroll_input_id)).fetchone()
        old = previous[0] if previous else "pending"
        db.execute("INSERT INTO approval_history(payroll_run_id,employee_id,payroll_input_id,reviewer_id,reviewer_role,previous_status,new_status,action_type,comments,exception_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (payroll_run_id,item["employee_id"],payroll_input_id,str(reviewer_id),role,old,status,"review",comments,exception_id))
        approval_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        _audit(db,"payroll_input",item["payroll_input_code"],"approval_"+status,reviewer_id,{"status":old},{"status":status,"role":role,"comments":comments,"exception_id":exception_id,"approval_id":approval_id})
        return {"approval_id":approval_id,"payroll_run_id":payroll_run_id,"payroll_input_id":payroll_input_id,"previous_status":old,"status":status,"reviewer_role":role}

def append_run_approvals(db, payroll_run_id, reviewer_id, role, comments=None):
    items = list(db.execute("SELECT pi.* FROM payroll_inputs pi JOIN payroll_run_inputs ri ON ri.employee_id=pi.employee_id AND ri.pay_period_id=pi.pay_period_id WHERE ri.payroll_run_id=?", (payroll_run_id,)))
    for item in items:
        prev = db.execute("SELECT new_status FROM approval_history WHERE payroll_run_id=? AND payroll_input_id=? ORDER BY approval_id DESC LIMIT 1",(payroll_run_id,item["payroll_input_id"])).fetchone()
        old = prev[0] if prev else "pending"
        if old in ("rejected","correction_required"): raise ValueError(f"Payroll input {item['payroll_input_code']} requires further review")
        if old == "approved": continue
        db.execute("INSERT INTO approval_history(payroll_run_id,employee_id,payroll_input_id,reviewer_id,reviewer_role,previous_status,new_status,action_type,comments) VALUES (?,?,?,?,?,?,?,?,?)",
                   (payroll_run_id,item["employee_id"],item["payroll_input_id"],str(reviewer_id),role,old,"approved","run_approval",comments))
        _audit(db,"payroll_input",item["payroll_input_code"],"approval_approved",reviewer_id,{"status":old},{"status":"approved","role":role,"comments":comments})

def submit_time_correction(payroll_input_id, time_entry_id, regular_hours, overtime_hours, employee_id,
                           reviewer_role="Employee", database_path=DATABASE_PATH, comments=None):
    role = require_role(reviewer_role, {"Employee", "Manager", "HR Partner"})
    with connect(database_path) as db:
        item = db.execute("SELECT * FROM payroll_inputs WHERE payroll_input_id=?",(payroll_input_id,)).fetchone()
        entry = db.execute("SELECT * FROM time_entries WHERE time_entry_id=?",(time_entry_id,)).fetchone()
        if item is None or entry is None: raise KeyError("Unknown payroll input or time entry")
        if item["employee_id"] != entry["employee_id"] or item["pay_period_id"] != entry["pay_period_id"]: raise ValueError("Time correction must match the payroll input employee and period")
        if role == "Employee" and str(employee_id) not in {str(item["employee_id"]), str(db.execute("SELECT employee_number FROM employees WHERE employee_id=?",(item["employee_id"],)).fetchone()[0])}: raise PermissionError("Employees may only correct their own records")
        latest = db.execute("SELECT new_status FROM approval_history WHERE payroll_input_id=? ORDER BY approval_id DESC LIMIT 1",(payroll_input_id,)).fetchone()
        if not latest or latest[0] != "correction_required": raise ValueError("A reviewer must request correction before correction submission")
    from payroll_validation.services.payroll_service import record_time_correction, process_payroll_period
    correction = record_time_correction(time_entry_id,regular_hours,overtime_hours,database_path,actor=str(employee_id))
    run = process_payroll_period(item["pay_period_id"],database_path,actor=str(employee_id))
    from payroll_validation.validators.validation_service import validate_payroll_run
    report = validate_payroll_run(run["payroll_run_id"],database_path,actor=str(employee_id))
    # Link the new run to the unchanged source payroll input and capture mandatory revalidation.
    with connect(database_path) as db:
        db.execute("INSERT INTO approval_history(payroll_run_id,employee_id,payroll_input_id,reviewer_id,reviewer_role,previous_status,new_status,action_type,comments) VALUES (?,?,?,?,?,?,?,?,?)",
                   (run["payroll_run_id"],item["employee_id"],payroll_input_id,str(employee_id),role,"correction_required","pending","correction_revalidated",comments))
        _audit(db,"payroll_input",item["payroll_input_code"],"correction_revalidated",employee_id,{"status":"correction_required"},{"status":"pending","new_payroll_run_id":run["payroll_run_id"],"time_entry_id":correction["time_entry_id"],"export_ready":report["export_ready"]})
    return {"correction":correction,"payroll_run":run,"validation":report}

def submit_source_correction(payroll_input_id, entity_type, entity_id, changes, employee_id,
                             reviewer_role="Employee", database_path=DATABASE_PATH, comments=None, payroll_run_id=None):
    """Submit an append-only correction for any supported payroll source, then revalidate a new run."""
    role=require_role(reviewer_role,{"Employee","Manager","HR Partner"})
    tables={"time_entry":("time_entries","time_entry_id"),"leave_record":("leave_records","leave_id"),
            "allowance":("allowances","allowance_id"),"deduction":("deductions","deduction_id")}
    if entity_type not in tables: raise ValueError("Unsupported correction entity type")
    table,pk=tables[entity_type]
    with connect(database_path) as db:
        item=db.execute("SELECT * FROM payroll_inputs WHERE payroll_input_id=?",(payroll_input_id,)).fetchone()
        source=db.execute(f"SELECT * FROM {table} WHERE {pk}=?",(entity_id,)).fetchone()
        if item is None or source is None: raise KeyError("Unknown payroll input or source record")
        if item["employee_id"]!=source["employee_id"] or item["pay_period_id"]!=source["pay_period_id"]:
            raise ValueError("Correction record must match the payroll input employee and period")
        if role=="Employee":
            employee_number=db.execute("SELECT employee_number FROM employees WHERE employee_id=?",(item["employee_id"],)).fetchone()[0]
            if str(employee_id) not in {str(item["employee_id"]),employee_number}: raise PermissionError("Employees may only correct their own records")
        if payroll_run_id is None:
            current=db.execute("SELECT payroll_run_id FROM payroll_runs WHERE pay_period_id=? ORDER BY run_number DESC LIMIT 1",(item["pay_period_id"],)).fetchone()
            payroll_run_id=current[0] if current else None
        previous=db.execute("SELECT new_status FROM approval_history WHERE payroll_input_id=? AND payroll_run_id=? ORDER BY approval_id DESC LIMIT 1",(payroll_input_id,payroll_run_id)).fetchone()
        if not previous or previous[0]!="correction_required": raise ValueError("A reviewer must request correction before correction submission")
    from payroll_validation.services import payroll_service
    handlers={"time_entry":lambda:payroll_service.record_time_correction(entity_id,changes["regular_hours"],changes.get("overtime_hours",0),database_path,str(employee_id)),
              "leave_record":lambda:payroll_service.record_leave_correction(entity_id,changes,database_path,str(employee_id)),
              "allowance":lambda:payroll_service.record_allowance_correction(entity_id,changes,database_path,str(employee_id)),
              "deduction":lambda:payroll_service.record_deduction_correction(entity_id,changes,database_path,str(employee_id))}
    correction=handlers[entity_type]()
    run=payroll_service.process_payroll_period(item["pay_period_id"],database_path,actor=str(employee_id))
    from payroll_validation.validators.validation_service import validate_payroll_run
    report=validate_payroll_run(run["payroll_run_id"],database_path,actor=str(employee_id))
    with connect(database_path) as db:
        db.execute("INSERT INTO approval_history(payroll_run_id,employee_id,payroll_input_id,reviewer_id,reviewer_role,previous_status,new_status,action_type,comments) VALUES (?,?,?,?,?,?,?,?,?)",
                   (run["payroll_run_id"],item["employee_id"],payroll_input_id,str(employee_id),role,"correction_required","pending","correction_revalidated",comments))
        _audit(db,"payroll_input",item["payroll_input_code"],"correction_revalidated",employee_id,{"status":"correction_required"},{"status":"pending","source_entity":entity_type,"source_id":entity_id,"new_payroll_run_id":run["payroll_run_id"],"export_ready":report["export_ready"]})
    return {"correction":correction,"payroll_run":run,"validation":report}

def _audit(db, entity_type, entity_id, action, actor, before, after):
    import json
    db.execute("INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) VALUES (?,?,?,?,?,?)",
               (entity_type,str(entity_id),action,str(actor),json.dumps(before,default=str),json.dumps(after,default=str)))
