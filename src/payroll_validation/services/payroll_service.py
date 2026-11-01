"""Immutable payroll run processing, approval and export controls."""
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from payroll_validation.config import DATABASE_PATH, EXPORT_DIR
from payroll_validation.database.connection import connect
from payroll_validation.services.reconciliation_service import source_components, calculate_pay_components


def process_payroll_period(pay_period_id, database_path=DATABASE_PATH, actor="payroll_service"):
    """Create a new payroll run from current source records; preserve older runs."""
    with connect(database_path) as db:
        period=db.execute("SELECT * FROM pay_periods WHERE pay_period_id=?",(pay_period_id,)).fetchone()
        if period is None:
            raise KeyError(f"Unknown pay_period_id {pay_period_id}")
        group=db.execute("SELECT overtime_multiplier FROM pay_groups WHERE pay_group_id=?",(period["pay_group_id"],)).fetchone()
        run_number=db.execute("SELECT COALESCE(MAX(run_number),0)+1 FROM payroll_runs WHERE pay_period_id=?",(pay_period_id,)).fetchone()[0]
        db.execute("INSERT INTO payroll_runs(pay_period_id,run_number,status,created_by) VALUES (?,?,'processed',?)",(pay_period_id,run_number,actor))
        run_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        employees=list(db.execute("SELECT * FROM employees WHERE pay_group_id=? AND employment_status='active' ORDER BY employee_number",(period["pay_group_id"],)))
        for employee in employees:
            source=source_components(db,employee["employee_id"],pay_period_id)
            calculated=calculate_pay_components(source,employee["hourly_rate"],group["overtime_multiplier"])
            details=json.dumps({"source":source,"hourly_rate":employee["hourly_rate"],"run_number":run_number},sort_keys=True,default=str)
            db.execute(
                "INSERT INTO payroll_run_inputs(payroll_run_id,employee_id,pay_period_id,regular_hours,overtime_hours,paid_leave_hours,allowance_total,deduction_total) VALUES (?,?,?,?,?,?,?,?)",
                (run_id,employee["employee_id"],pay_period_id,source["regular_hours"],source["overtime_hours"],source["paid_leave_hours"],float(source["allowance_total"]),float(source["deduction_total"])),
            )
            payroll_run_input_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                "INSERT INTO payroll_results(payroll_run_input_id,payroll_run_id,employee_id,regular_hours,overtime_hours,regular_pay,overtime_pay,allowance_total,deduction_total,gross_pay,net_pay,calculation_details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (payroll_run_input_id,run_id,employee["employee_id"],calculated["regular_hours"],calculated["overtime_hours"],
                 float(calculated["regular_pay"]),float(calculated["overtime_pay"]),float(calculated["allowance_total"]),
                 float(calculated["deduction_total"]),float(calculated["gross_pay"]),float(calculated["net_pay"]),details),
            )
        _audit(db,"payroll_run",run_id,"payroll_run_processed",actor,None,{"run_number":run_number,"pay_period_id":pay_period_id,"employee_count":len(employees)})
        return {"payroll_run_id":run_id,"pay_period_id":pay_period_id,"run_number":run_number,"employee_count":len(employees),"status":"processed"}


def record_time_correction(time_entry_id, regular_hours, overtime_hours, database_path=DATABASE_PATH, actor="payroll_service"):
    """Append a superseding time record without changing the original submission."""
    if regular_hours < 0 or overtime_hours < 0:
        raise ValueError("Corrected hours cannot be negative")
    with connect(database_path) as db:
        original=db.execute("SELECT * FROM time_entries WHERE time_entry_id=?",(time_entry_id,)).fetchone()
        if original is None:
            raise KeyError(f"Unknown time_entry_id {time_entry_id}")
        employee_number=db.execute("SELECT employee_number FROM employees WHERE employee_id=?",(original["employee_id"],)).fetchone()[0]
        sequence=db.execute("SELECT COUNT(*)+1 FROM time_entries WHERE supersedes_time_entry_id=?",(time_entry_id,)).fetchone()[0]
        code=f"TIME-{employee_number}-{original['work_date']}-CORR-{sequence:05d}"
        db.execute(
            "INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type,supersedes_time_entry_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (original["employee_id"],original["pay_period_id"],original["work_date"],code,regular_hours,overtime_hours,
             "manual_correction","approved","approved","correction",time_entry_id),
        )
        new_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        _audit(db,"time_entry",code,"correction_added",actor,dict(original),{"time_entry_id":new_id,"supersedes_time_entry_id":time_entry_id,"regular_hours":regular_hours,"overtime_hours":overtime_hours})
        return {"time_entry_id":new_id,"time_entry_code":code,"supersedes_time_entry_id":time_entry_id}


def record_leave_correction(leave_id, changes, database_path=DATABASE_PATH, actor="payroll_service"):
    """Append a corrected leave version; the original row remains immutable."""
    with connect(database_path) as db:
        old=db.execute("SELECT * FROM leave_records WHERE leave_id=?",(leave_id,)).fetchone()
        if old is None: raise KeyError(f"Unknown leave_id {leave_id}")
        values={key:changes.get(key,old[key]) for key in ("leave_type","start_date","end_date","hours","status")}
        if values["end_date"] < values["start_date"] or float(values["hours"]) < 0: raise ValueError("Corrected leave dates or hours are invalid")
        db.execute("INSERT INTO leave_records(employee_id,pay_period_id,leave_type,start_date,end_date,hours,status,supersedes_leave_id) VALUES (?,?,?,?,?,?,?,?)",
                   (old["employee_id"],old["pay_period_id"],values["leave_type"],values["start_date"],values["end_date"],values["hours"],values["status"],leave_id))
        new_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        _audit(db,"leave_record",new_id,"correction_added",actor,dict(old),{**values,"supersedes_leave_id":leave_id})
        return {"leave_id":new_id,"supersedes_leave_id":leave_id,"pay_period_id":old["pay_period_id"],"employee_id":old["employee_id"]}


def record_allowance_correction(allowance_id, changes, database_path=DATABASE_PATH, actor="payroll_service"):
    """Append a corrected allowance version without overwriting its source row."""
    with connect(database_path) as db:
        old=db.execute("SELECT * FROM allowances WHERE allowance_id=?",(allowance_id,)).fetchone()
        if old is None: raise KeyError(f"Unknown allowance_id {allowance_id}")
        amount=float(changes.get("amount",old["amount"]))
        if amount < 0: raise ValueError("Corrected allowance amount cannot be negative")
        seq=db.execute("SELECT COALESCE(MAX(allowance_id),0)+1 FROM allowances").fetchone()[0]
        code=f"ALW-CORR-{seq:08d}"
        db.execute("INSERT INTO allowances(employee_id,pay_period_id,allowance_type,allowance_code,source_reference,submission_type,amount,taxable,eligible,description,supersedes_allowance_id) VALUES (?,?,?,?,?,'correction',?,?,?,?,?)",
                   (old["employee_id"],old["pay_period_id"],changes.get("allowance_type",old["allowance_type"]),code,old["source_reference"],amount,changes.get("taxable",old["taxable"]),changes.get("eligible",old["eligible"]),changes.get("description",old["description"]),allowance_id))
        new_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        _audit(db,"allowance",code,"correction_added",actor,dict(old),{"allowance_id":new_id,"supersedes_allowance_id":allowance_id,"amount":amount})
        return {"allowance_id":new_id,"allowance_code":code,"supersedes_allowance_id":allowance_id,"pay_period_id":old["pay_period_id"],"employee_id":old["employee_id"]}


def record_deduction_correction(deduction_id, changes, database_path=DATABASE_PATH, actor="payroll_service"):
    """Append a corrected deduction version without overwriting its source row."""
    with connect(database_path) as db:
        old=db.execute("SELECT * FROM deductions WHERE deduction_id=?",(deduction_id,)).fetchone()
        if old is None: raise KeyError(f"Unknown deduction_id {deduction_id}")
        amount=float(changes.get("amount",old["amount"]))
        if amount < 0: raise ValueError("Corrected deduction amount cannot be negative")
        seq=db.execute("SELECT COALESCE(MAX(deduction_id),0)+1 FROM deductions").fetchone()[0]
        code=f"DED-CORR-{seq:08d}"
        db.execute("INSERT INTO deductions(employee_id,pay_period_id,deduction_type,deduction_code,source_reference,leave_id,submission_type,amount,pre_tax,description,supersedes_deduction_id) VALUES (?,?,?,?,?,?, 'correction',?,?,?,?)",
                   (old["employee_id"],old["pay_period_id"],changes.get("deduction_type",old["deduction_type"]),code,old["source_reference"],changes.get("leave_id",old["leave_id"]),amount,changes.get("pre_tax",old["pre_tax"]),changes.get("description",old["description"]),deduction_id))
        new_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        _audit(db,"deduction",code,"correction_added",actor,dict(old),{"deduction_id":new_id,"supersedes_deduction_id":deduction_id,"amount":amount})
        return {"deduction_id":new_id,"deduction_code":code,"supersedes_deduction_id":deduction_id,"pay_period_id":old["pay_period_id"],"employee_id":old["employee_id"]}


def approve_payroll_run(payroll_run_id, approver, database_path=DATABASE_PATH, comments=None, reviewer_role="HR Partner", require_explicit_input_approval=False):
    """Revalidate immediately before approval and persist per-input audit history."""
    from payroll_validation.validators.validation_service import validate_payroll_run
    from payroll_validation.services.roles import require_role
    role = require_role(reviewer_role, {"Manager", "HR Partner"})
    report=validate_payroll_run(payroll_run_id,database_path,actor=approver)
    if not report["export_ready"]:
        raise ValueError(f"Payroll run has {report['total_exceptions']} unresolved critical exception(s); approval blocked")
    with connect(database_path) as db:
        run=db.execute("SELECT status FROM payroll_runs WHERE payroll_run_id=?",(payroll_run_id,)).fetchone()
        if run is None:
            raise KeyError(f"Unknown payroll_run_id {payroll_run_id}")
        if run["status"]!="validated":
            raise ValueError(f"Payroll run must be validated before approval (status={run['status']})")
        if require_explicit_input_approval:
            pending=db.execute(
                "SELECT pi.payroll_input_code FROM payroll_run_inputs ri JOIN payroll_inputs pi ON pi.employee_id=ri.employee_id AND pi.pay_period_id=ri.pay_period_id "
                "WHERE ri.payroll_run_id=? AND COALESCE((SELECT ah.new_status FROM approval_history ah WHERE ah.payroll_run_id=ri.payroll_run_id AND ah.payroll_input_id=pi.payroll_input_id ORDER BY ah.approval_id DESC LIMIT 1),'pending')!='approved' LIMIT 1",
                (payroll_run_id,),
            ).fetchone()
            if pending: raise ValueError(f"Payroll input {pending[0]} has not been individually approved")
        from payroll_validation.approvals.approval_service import append_run_approvals
        append_run_approvals(db,payroll_run_id,approver,role,comments)
        db.execute("INSERT INTO approvals(payroll_run_id,approver,decision,comments) VALUES (?,?,'approved',?)",(payroll_run_id,approver,comments))
        db.execute("UPDATE payroll_runs SET status='approved' WHERE payroll_run_id=?",(payroll_run_id,))
        _audit(db,"payroll_run",payroll_run_id,"payroll_run_approved",approver,{"status":"validated"},{"status":"approved","comments":comments})
        return {"payroll_run_id":payroll_run_id,"status":"approved","approver":approver}


def export_payroll_run(payroll_run_id, output_path=None, database_path=DATABASE_PATH, actor="payroll_service", output_format="csv"):
    """Revalidate and export only fully approved, currently clean payroll inputs."""
    output_format=str(output_format).lower()
    if output_format not in {"csv","json","xlsx"}: raise ValueError("Payroll export format must be CSV, JSON, or XLSX")
    from payroll_validation.validators.validation_service import validate_payroll_run
    report=validate_payroll_run(payroll_run_id,database_path,actor=actor)
    if not report["export_ready"]:
        raise ValueError("Export blocked: unresolved critical payroll exceptions remain")
    with connect(database_path) as db:
        run=db.execute("SELECT status FROM payroll_runs WHERE payroll_run_id=?",(payroll_run_id,)).fetchone()
        approval=db.execute("SELECT approval_id FROM approvals WHERE payroll_run_id=? AND decision='approved' ORDER BY decided_at DESC LIMIT 1",(payroll_run_id,)).fetchone()
        already_exported=db.execute("SELECT export_id FROM payroll_exports WHERE payroll_run_id=?",(payroll_run_id,)).fetchone()
        if run is None:
            raise KeyError(f"Unknown payroll_run_id {payroll_run_id}")
        if already_exported:
            raise ValueError("Export blocked: this payroll run has already been exported")
        if run["status"]!="approved" or approval is None:
            raise ValueError("Export blocked: payroll run must have a current approval")
        not_approved=db.execute(
            "SELECT pi.payroll_input_code FROM payroll_run_inputs ri JOIN payroll_inputs pi ON pi.employee_id=ri.employee_id AND pi.pay_period_id=ri.pay_period_id "
            "WHERE ri.payroll_run_id=? AND COALESCE((SELECT ah.new_status FROM approval_history ah WHERE ah.payroll_run_id=ri.payroll_run_id AND ah.payroll_input_id=pi.payroll_input_id ORDER BY ah.approval_id DESC LIMIT 1),'pending')!='approved' LIMIT 1",
            (payroll_run_id,),
        ).fetchone()
        if not_approved: raise ValueError(f"Export blocked: payroll input {not_approved[0]} is not approved")
        rows=[dict(row) for row in db.execute(
            "SELECT e.employee_number,p.pay_period_code,pr.regular_hours,pr.overtime_hours,pr.regular_pay,pr.overtime_pay,pr.allowance_total,pr.deduction_total,pr.gross_pay,pr.net_pay "
            "FROM payroll_results pr JOIN payroll_runs r USING(payroll_run_id) JOIN pay_periods p USING(pay_period_id) "
            "JOIN employees e USING(employee_id) WHERE pr.payroll_run_id=? ORDER BY e.employee_number",(payroll_run_id,),
        )]
    path=Path(output_path) if output_path else EXPORT_DIR/f"payroll-run-{payroll_run_id}.{output_format}"
    if path.exists(): raise ValueError(f"Export blocked: output file already exists: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    if output_format=="json":
        with path.open("w",encoding="utf-8") as stream: json.dump(rows,stream,indent=2)
    elif output_format=="xlsx":
        pd.DataFrame(rows).to_excel(path,index=False,engine="openpyxl",sheet_name="Approved Payroll")
    else:
        with path.open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]) if rows else ["employee_number","pay_period_code","net_pay"])
            writer.writeheader(); writer.writerows(rows)
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    with connect(database_path) as db:
        db.execute("INSERT INTO payroll_exports(payroll_run_id,file_path,format,exported_by,record_count,checksum) VALUES (?,?,?,?,?,?)",
                   (payroll_run_id,str(path),output_format,actor,len(rows),checksum))
        _audit(db,"payroll_run",payroll_run_id,"payroll_export_created",actor,None,{"file_path":str(path),"format":output_format,"record_count":len(rows),"checksum":checksum})
        db.execute("UPDATE payroll_runs SET status='exported' WHERE payroll_run_id=?",(payroll_run_id,))
    return {"payroll_run_id":payroll_run_id,"path":str(path),"format":output_format,"record_count":len(rows),"checksum":checksum,
            "summary":{"employee_records":len(rows),"gross_pay":round(sum(r["gross_pay"] for r in rows),2),
                       "allowances":round(sum(r["allowance_total"] for r in rows),2),
                       "deductions":round(sum(r["deduction_total"] for r in rows),2),
                       "net_pay":round(sum(r["net_pay"] for r in rows),2)}}


def _audit(db,entity_type,entity_id,action,actor,before,after):
    db.execute("INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) VALUES (?,?,?,?,?,?)",
               (entity_type,str(entity_id),action,actor,json.dumps(before,sort_keys=True,default=str) if before is not None else None,json.dumps(after,sort_keys=True,default=str) if after is not None else None))
