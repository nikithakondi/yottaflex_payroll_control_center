"""Database-backed CRUD for payroll master and source records."""
import json

from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect

def create_employee(values, database_path=DATABASE_PATH, actor="streamlit_user"):
    with connect(database_path) as db:
        group=db.execute("SELECT pay_group_id FROM pay_groups WHERE pay_group_id=?",(values["pay_group_id"],)).fetchone()
        if not group: raise ValueError("Select an existing pay group")
        number=values.get("employee_number") or f"EMP-{db.execute('SELECT COALESCE(MAX(CAST(substr(employee_number,5) AS INTEGER)),0)+1 FROM employees').fetchone()[0]:06d}"
        department=values["department"].strip()
        db.execute("INSERT OR IGNORE INTO departments(department_name) VALUES (?)",(department,))
        department_id=db.execute("SELECT department_id FROM departments WHERE department_name=?",(department,)).fetchone()[0]
        salary=float(values["annual_salary"]); rate=float(values.get("hourly_rate") or salary/2080)
        if salary<0 or rate<0: raise ValueError("Salary and hourly rate cannot be negative")
        db.execute("INSERT INTO employees(employee_number,first_name,last_name,email,department,department_id,job_title,hire_date,pay_group_id,employment_status,standard_hours,annual_salary,hourly_rate,bank_account_token,tax_info_token) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (number,values["first_name"].strip(),values["last_name"].strip(),values["email"].strip(),department,department_id,values["job_title"].strip(),values["hire_date"],values["pay_group_id"],values.get("employment_status","active"),float(values.get("standard_hours",40)),salary,rate,values.get("bank_account_token"),values.get("tax_info_token")))
        employee_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        _audit(db,"employee",number,"employee_created",actor,None,values)
        return employee_id

def update_employee(employee_id, changes, database_path=DATABASE_PATH, actor="streamlit_user"):
    allowed={"department","job_title","employment_status","bank_account_token","tax_info_token","termination_date"}
    if not changes or set(changes)-allowed: raise ValueError("Employee update contains unsupported fields")
    with connect(database_path) as db:
        old=db.execute("SELECT * FROM employees WHERE employee_id=?",(employee_id,)).fetchone()
        if old is None: raise KeyError("Employee not found")
        changes=dict(changes)
        if "department" in changes:
            department=changes["department"].strip()
            db.execute("INSERT OR IGNORE INTO departments(department_name) VALUES (?)",(department,))
            changes["department_id"]=db.execute("SELECT department_id FROM departments WHERE department_name=?",(department,)).fetchone()[0]
        cols=list(changes)
        db.execute("UPDATE employees SET "+",".join(f"{c}=?" for c in cols)+" WHERE employee_id=?",(*[changes[c] for c in cols],employee_id))
        _audit(db,"employee",old["employee_number"],"employee_updated",actor,dict(old),changes)

def create_pay_group(values, database_path=DATABASE_PATH, actor="streamlit_user"):
    with connect(database_path) as db:
        db.execute("INSERT INTO pay_groups(code,name,pay_frequency,currency,standard_hours,overtime_multiplier,max_period_hours) VALUES (?,?,?,?,?,?,?)",
                   (values["code"],values["name"],values.get("pay_frequency","monthly"),values.get("currency","USD"),values.get("standard_hours",40),values.get("overtime_multiplier",1.5),values.get("max_period_hours",200)))
        key=db.execute("SELECT last_insert_rowid()").fetchone()[0]; _audit(db,"pay_group",key,"pay_group_created",actor,None,values); return key

def create_pay_period(values, database_path=DATABASE_PATH, actor="streamlit_user"):
    if values["period_start"]>values["period_end"] or values["payment_date"]<values["period_end"]: raise ValueError("Pay period dates are inconsistent")
    with connect(database_path) as db:
        db.execute("INSERT INTO pay_periods(pay_group_id,period_start,period_end,payment_date,pay_period_code,status) VALUES (?,?,?,?,?,'open')",
                   (values["pay_group_id"],values["period_start"],values["period_end"],values["payment_date"],values["pay_period_code"]))
        key=db.execute("SELECT last_insert_rowid()").fetchone()[0]; _audit(db,"pay_period",key,"pay_period_created",actor,None,values); return key

def create_time_entry(values, database_path=DATABASE_PATH, actor="streamlit_user"):
    if float(values["regular_hours"])<0 or float(values.get("overtime_hours",0))<0: raise ValueError("Hours cannot be negative")
    with connect(database_path) as db:
        employee=db.execute("SELECT employee_number,pay_group_id FROM employees WHERE employee_id=?",(values["employee_id"],)).fetchone()
        period=db.execute("SELECT pay_period_code,pay_group_id FROM pay_periods WHERE pay_period_id=?",(values["pay_period_id"],)).fetchone()
        if not employee or not period or employee["pay_group_id"]!=period["pay_group_id"]: raise ValueError("Employee and pay-period references must exist and belong to the same pay group")
        code=values.get("time_entry_code") or f"TIME-{employee['employee_number']}-{values['work_date']}"
        db.execute("INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status) VALUES (?,?,?,?,?,?,?,'submitted','pending')",
                   (values["employee_id"],values["pay_period_id"],values["work_date"],code,values["regular_hours"],values.get("overtime_hours",0),values.get("source","manual_entry")))
        key=db.execute("SELECT last_insert_rowid()").fetchone()[0]; _audit(db,"time_entry",code,"time_entry_submitted",actor,None,values); return key

def create_leave_record(values, database_path=DATABASE_PATH, actor="streamlit_user"):
    if values["start_date"]>values["end_date"] or float(values["hours"])<0: raise ValueError("Leave dates or hours are invalid")
    with connect(database_path) as db:
        db.execute("INSERT INTO leave_records(employee_id,pay_period_id,leave_type,start_date,end_date,hours,status) VALUES (?,?,?,?,?,?,'pending')",
                   (values["employee_id"],values["pay_period_id"],values["leave_type"],values["start_date"],values["end_date"],values["hours"]))
        key=db.execute("SELECT last_insert_rowid()").fetchone()[0]; _audit(db,"leave_record",key,"leave_submitted",actor,None,values); return key

def create_allowance(values, database_path=DATABASE_PATH, actor="streamlit_user"):
    if float(values["amount"])<0: raise ValueError("Allowance cannot be negative")
    with connect(database_path) as db:
        code=values.get("allowance_code") or f"ALW-MAN-{db.execute('SELECT COALESCE(MAX(allowance_id),0)+1 FROM allowances').fetchone()[0]:08d}"
        source=values.get("source_reference") or code
        db.execute("INSERT INTO allowances(employee_id,pay_period_id,allowance_type,allowance_code,source_reference,amount,taxable,eligible,description) VALUES (?,?,?,?,?,?,?,?,?)",
                   (values["employee_id"],values["pay_period_id"],values["allowance_type"],code,source,values["amount"],values.get("taxable",1),values.get("eligible",1),values.get("description")))
        key=db.execute("SELECT last_insert_rowid()").fetchone()[0]; _audit(db,"allowance",code,"allowance_created",actor,None,values); return key

def create_deduction(values, database_path=DATABASE_PATH, actor="streamlit_user"):
    if float(values["amount"])<0: raise ValueError("Deduction cannot be negative")
    with connect(database_path) as db:
        code=values.get("deduction_code") or f"DED-MAN-{db.execute('SELECT COALESCE(MAX(deduction_id),0)+1 FROM deductions').fetchone()[0]:08d}"
        source=values.get("source_reference") or code
        db.execute("INSERT INTO deductions(employee_id,pay_period_id,deduction_type,deduction_code,source_reference,leave_id,amount,pre_tax,description) VALUES (?,?,?,?,?,?,?,?,?)",
                   (values["employee_id"],values["pay_period_id"],values["deduction_type"],code,source,values.get("leave_id"),values["amount"],values.get("pre_tax",0),values.get("description")))
        key=db.execute("SELECT last_insert_rowid()").fetchone()[0]; _audit(db,"deduction",code,"deduction_created",actor,None,values); return key

def set_time_approval(time_entry_id, status, reviewer, database_path=DATABASE_PATH):
    if status not in {"approved","rejected"}: raise ValueError("Time entry decision must be approved or rejected")
    with connect(database_path) as db:
        row=db.execute("SELECT * FROM time_entries WHERE time_entry_id=?",(time_entry_id,)).fetchone()
        if row is None: raise KeyError("Time entry not found")
        db.execute("UPDATE time_entries SET status=?,approval_status=? WHERE time_entry_id=?",(status,status,time_entry_id))
        _audit(db,"time_entry",row["time_entry_code"],"time_entry_"+status,reviewer,{"status":row["status"],"approval_status":row["approval_status"]},{"status":status,"approval_status":status})

def set_leave_status(leave_id,status,reviewer,database_path=DATABASE_PATH):
    if status not in {"approved","rejected"}: raise ValueError("Leave decision must be approved or rejected")
    with connect(database_path) as db:
        row=db.execute("SELECT * FROM leave_records WHERE leave_id=?",(leave_id,)).fetchone()
        if row is None: raise KeyError("Leave record not found")
        if row["status"]!="pending": raise ValueError("Only pending leave can be reviewed")
        db.execute("UPDATE leave_records SET status=? WHERE leave_id=?",(status,leave_id))
        _audit(db,"leave_record",leave_id,"leave_"+status,reviewer,{"status":row["status"]},{"status":status})

def _audit(db, entity_type, entity_id, action, actor, before, after):
    db.execute("INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) VALUES (?,?,?,?,?,?)",
               (entity_type,str(entity_id),action,str(actor),json.dumps(before,default=str) if before is not None else None,json.dumps(after,default=str) if after is not None else None))
