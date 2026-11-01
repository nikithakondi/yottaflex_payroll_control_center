"""Create, deduplicate, resolve and audit validation exceptions."""
import hashlib
import json

from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect


def record_findings(db, payroll_run_id, findings, actor="validation_service"):
    """Persist current findings, reopen corrected findings and resolve stale ones."""
    active_keys = set()
    exception_rows = []
    for finding in findings:
        key = _finding_key(finding,payroll_run_id)
        active_keys.add(key)
        expected = _json(finding.get("expected_value"))
        actual = _json(finding.get("actual_value"))
        details = _json(finding.get("details", {}))
        existing = db.execute("SELECT * FROM exceptions WHERE finding_key=?", (key,)).fetchone()
        after = {
            "finding_key":key,"rule_code":finding["rule_code"],"severity":finding["severity"],
            "message":finding["message"],"expected_value":expected,"actual_value":actual,"status":"open",
        }
        if existing is None:
            exception_code = _next_exception_code(db)
            rule_id = db.execute("SELECT validation_rule_id FROM validation_rules WHERE rule_code=?", (finding["rule_code"],)).fetchone()
            db.execute(
                "INSERT INTO exceptions(exception_code,finding_key,anomaly_label,payroll_run_id,employee_id,employee_reference,"
                "pay_period_id,pay_period_reference,entity_type,entity_id,rule_code,validation_rule_id,severity,message,expected_value,actual_value,"
                "details_json,status,workflow_status,detected_at,last_detected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open','open',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                (exception_code,key,finding["rule_code"],payroll_run_id,finding.get("employee_id"),
                 finding.get("employee_reference"),finding.get("pay_period_id"),finding.get("pay_period_reference"),
                 finding["entity_type"],str(finding["entity_id"]),finding["rule_code"],rule_id[0] if rule_id else None,finding["severity"],
                 finding["message"],expected,actual,details),
            )
            _audit(db,"exception",exception_code,"exception_detected",actor,None,after)
        else:
            before = _exception_snapshot(existing)
            db.execute(
                "UPDATE exceptions SET anomaly_label=?,employee_id=?,employee_reference=?,pay_period_id=?,pay_period_reference=?,"
                "entity_type=?,entity_id=?,validation_rule_id=(SELECT validation_rule_id FROM validation_rules WHERE rule_code=?),severity=?,message=?,expected_value=?,actual_value=?,details_json=?,status='open',workflow_status='open',"
                "resolution=NULL,resolved_at=NULL,last_detected_at=CURRENT_TIMESTAMP WHERE exception_id=?",
                (finding["rule_code"],finding.get("employee_id"),finding.get("employee_reference"),
                 finding.get("pay_period_id"),finding.get("pay_period_reference"),finding["entity_type"],
                 str(finding["entity_id"]),finding["rule_code"],finding["severity"],finding["message"],expected,actual,details,existing["exception_id"]),
            )
            after.update({"exception_code":existing["exception_code"],"status":"open"})
            if before != after:
                _audit(db,"exception",existing["exception_code"],"exception_refreshed",actor,before,after)

    for stale in list(db.execute(
        "SELECT * FROM exceptions WHERE payroll_run_id=? AND workflow_status IN ('open','under_review','rejected')",(payroll_run_id,)
    )):
        if stale["finding_key"] in active_keys:
            continue
        before = _exception_snapshot(stale)
        db.execute(
            "UPDATE exceptions SET status='resolved',workflow_status='resolved',resolution='No longer detected during revalidation',resolved_at=CURRENT_TIMESTAMP,last_detected_at=CURRENT_TIMESTAMP WHERE exception_id=?",
            (stale["exception_id"],),
        )
        after = {**before,"status":"resolved","resolution":"No longer detected during revalidation"}
        _audit(db,"exception",stale["exception_code"],"exception_resolved_by_revalidation",actor,before,after)

    for finding in findings:
        row = db.execute("SELECT * FROM exceptions WHERE finding_key=?",(_finding_key(finding,payroll_run_id),)).fetchone()
        exception_rows.append(dict(row))
    return exception_rows


def resolve_exception(exception_id, resolution, actor, database_path=DATABASE_PATH, waived=False):
    """Resolve or waive a finding without deleting its record or audit history."""
    if not resolution or not resolution.strip():
        raise ValueError("A resolution comment is required")
    new_status = "waived" if waived else "resolved"
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM exceptions WHERE exception_id=?",(exception_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown exception_id {exception_id}")
        before = _exception_snapshot(row)
        db.execute(
            "UPDATE exceptions SET status=?,workflow_status=?,resolution=?,resolved_at=CURRENT_TIMESTAMP WHERE exception_id=?",
            (new_status,"rejected" if waived else "resolved",resolution.strip(),exception_id),
        )
        _audit(db,"exception",row["exception_code"],"exception_waived" if waived else "exception_resolved",actor,
               before,{**before,"status":new_status,"resolution":resolution.strip()})
        return dict(db.execute("SELECT * FROM exceptions WHERE exception_id=?",(exception_id,)).fetchone())


TECHNICAL_RULES = {"INVALID_REFERENCE", "DUPLICATE_TIME_ENTRY", "INCORRECT_PAYROLL_CALCULATION", "PAYROLL_RECONCILIATION"}

def assign_exception(exception_id, assignee_id, assignee_role, assigned_by, assigned_by_role,
                     database_path=DATABASE_PATH, comments=None):
    from payroll_validation.services.roles import require_role
    assignee_role = require_role(assignee_role, {"Employee", "Manager", "HR Partner", "IT/Operations Partner", "System Administrator"})
    assigned_by_role = require_role(assigned_by_role, {"Manager", "HR Partner", "IT/Operations Partner", "System Administrator"})
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM exceptions WHERE exception_id=?",(exception_id,)).fetchone()
        if row is None: raise KeyError(f"Unknown exception_id {exception_id}")
        db.execute("INSERT INTO exception_assignments(exception_id,assignee_id,assignee_role,assigned_by,assigned_by_role,comments) VALUES (?,?,?,?,?,?)",
                   (exception_id,str(assignee_id),assignee_role,str(assigned_by),assigned_by_role,comments))
        assignment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE exceptions SET workflow_status='under_review',status='under_review' WHERE exception_id=? AND status='open'",(exception_id,))
        _audit(db,"exception",row["exception_code"],"exception_assigned",assigned_by,_exception_snapshot(row),{"assignee_id":str(assignee_id),"assignee_role":assignee_role,"comments":comments})
        return dict(db.execute("SELECT * FROM exception_assignments WHERE assignment_id=?",(assignment_id,)).fetchone())

def review_exception(exception_id, reviewer_id, reviewer_role, new_status, comments, database_path=DATABASE_PATH):
    from payroll_validation.services.roles import require_role
    role = require_role(reviewer_role, {"Manager", "HR Partner", "IT/Operations Partner", "System Administrator"})
    status = str(new_status).strip().lower().replace(" ", "_")
    if status not in {"under_review", "resolved", "rejected"}: raise ValueError("Exception status must be Under Review, Resolved, or Rejected")
    if not comments or not comments.strip(): raise ValueError("Review comments are required")
    with connect(database_path) as db:
        row = db.execute("SELECT * FROM exceptions WHERE exception_id=?",(exception_id,)).fetchone()
        if row is None: raise KeyError(f"Unknown exception_id {exception_id}")
        if role == "IT/Operations Partner" and row["rule_code"] not in TECHNICAL_RULES: raise PermissionError("IT/Operations Partner may only resolve technical exceptions")
        assignment = db.execute("SELECT assignee_id,assignee_role FROM exception_assignments WHERE exception_id=? ORDER BY assignment_id DESC LIMIT 1",(exception_id,)).fetchone()
        if assignment and str(reviewer_id) != assignment["assignee_id"] and role not in {"HR Partner","System Administrator"}:
            raise PermissionError("Only the assigned reviewer, HR Partner, or System Administrator may review this exception")
        old = row["workflow_status"] if "workflow_status" in row.keys() else row["status"]
        db.execute("INSERT INTO exception_review_history(exception_id,reviewer_id,reviewer_role,previous_status,new_status,comments) VALUES (?,?,?,?,?,?)",
                   (exception_id,str(reviewer_id),role,old,status,comments.strip()))
        legacy = {"under_review":"under_review","resolved":"resolved","rejected":"waived"}[status]
        resolved_sql = ",resolved_at=CURRENT_TIMESTAMP" if status in {"resolved","rejected"} else ""
        db.execute(f"UPDATE exceptions SET workflow_status=?,status=?,resolution=?{resolved_sql} WHERE exception_id=?",(status,legacy,comments.strip(),exception_id))
        _audit(db,"exception",row["exception_code"],"exception_"+status,reviewer_id,_exception_snapshot(row),{"workflow_status":status,"reviewer_role":role,"comments":comments.strip()})
        return dict(db.execute("SELECT * FROM exceptions WHERE exception_id=?",(exception_id,)).fetchone())


def list_exceptions(database_path=DATABASE_PATH, payroll_run_id=None, status=None):
    clauses, params = [], []
    if payroll_run_id is not None:
        clauses.append("payroll_run_id=?"); params.append(payroll_run_id)
    if status is not None:
        clauses.append("status=?"); params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect(database_path) as db:
        return [dict(row) for row in db.execute(f"SELECT * FROM exceptions{where} ORDER BY exception_id",params)]


def _next_exception_code(db):
    largest = db.execute(
        "SELECT COALESCE(MAX(CAST(substr(exception_code,10) AS INTEGER)),0) FROM exceptions WHERE exception_code LIKE 'PEX-2026-%'"
    ).fetchone()[0]
    return f"PEX-2026-{largest+1:06d}"


def _finding_key(finding,payroll_run_id=None):
    fields = (finding["rule_code"],finding["entity_type"],str(finding["entity_id"]),
              str(finding.get("employee_reference") or ""),str(finding.get("pay_period_reference") or ""),str(payroll_run_id or ""))
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()


def _json(value):
    if value is None:
        return None
    return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)


def _exception_snapshot(row):
    return {key:row[key] for key in ("exception_code","rule_code","severity","message","expected_value","actual_value","status","resolution")}


def _audit(db,entity_type,entity_id,action,actor,before,after):
    db.execute(
        "INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) VALUES (?,?,?,?,?,?)",
        (entity_type,str(entity_id),action,actor,_json(before),_json(after)),
    )
