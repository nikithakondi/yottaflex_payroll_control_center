"""Inject five labeled payroll anomalies and produce independent ground truth."""

ANOMALY_RULES = (
    ("HOURS_PERIOD_MAX", "Hours exceeding the pay-period maximum", "BLOCK_EXPORT"),
    ("DUPLICATE_ALLOWANCE", "Duplicate allowance submissions", "BLOCK_EXPORT"),
    ("TIME_UNAPPROVED", "Unapproved time entries", "BLOCK_EXPORT"),
    ("DUP_UNPAID_LEAVE_DEDUCTION", "Duplicate unpaid leave deductions", "BLOCK_EXPORT"),
    ("PAYROLL_RECONCILIATION", "Payroll totals failing reconciliation", "BLOCK_EXPORT"),
)
GROUND_TRUTH_COLUMNS = [
    "anomaly_id", "employee_id", "pay_period_id", "issue_type",
    "expected_validation_result", "expected_decision",
]


def inject_source_anomalies(db, source_metadata):
    """Add four source-side anomalies after valid source records are generated."""
    employees = [dict(row) for row in db.execute(
        "SELECT employee_id,employee_number,pay_group_id,hourly_rate FROM employees ORDER BY employee_number"
    )]
    if len(employees) < 5:
        raise ValueError("At least five employees are required to build anomaly scenarios")
    time_seq = source_metadata["time_seq"]
    allowance_seq = source_metadata["allowance_seq"]
    deduction_seq = source_metadata["deduction_seq"]

    def period_for(employee, month):
        row = db.execute(
            "SELECT pay_period_id,pay_period_code,period_start FROM pay_periods WHERE pay_group_id=? AND pay_period_code=?",
            (employee["pay_group_id"], f"PP-2026-{month:02d}"),
        ).fetchone()
        if row is None:
            raise ValueError(f"Missing month {month} pay period for {employee['employee_number']}")
        return dict(row)

    facts = []
    # 1. Approved but excessive hours. This makes a real source record exceed
    #    the configured 200-hour period limit.
    employee = employees[0]
    period = period_for(employee, 1)
    time_seq += 1
    db.execute(
        "INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (employee["employee_id"],period["pay_period_id"],period["period_start"],f"TIME-{employee['employee_number']}-{period['period_start']}",250.0,0.0,"anomaly_hours_over_max","approved","approved","original"),
    )
    facts.append(_fact("HOURS_PERIOD_MAX", employee, period))

    # 2. Copy a valid allowance with its same source reference and amount.
    allowance = dict(db.execute("SELECT * FROM allowances ORDER BY allowance_id LIMIT 1").fetchone())
    allowance_seq += 1
    allowance_employee = next(e for e in employees if e["employee_id"] == allowance["employee_id"])
    allowance_period = dict(db.execute("SELECT * FROM pay_periods WHERE pay_period_id=?", (allowance["pay_period_id"],)).fetchone())
    db.execute(
        "INSERT INTO allowances(employee_id,pay_period_id,allowance_type,allowance_code,source_reference,submission_type,amount,taxable,eligible,description) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (allowance["employee_id"],allowance["pay_period_id"],allowance["allowance_type"],f"ALW-2026-{allowance_seq:07d}",allowance["source_reference"],"duplicate",allowance["amount"],allowance["taxable"],allowance["eligible"],allowance["description"]),
    )
    facts.append(_fact("DUPLICATE_ALLOWANCE", allowance_employee, allowance_period))

    # 3. Explicitly pending time; payroll input aggregation excludes it.
    employee = employees[1]
    period = period_for(employee, 2)
    time_seq += 1
    db.execute(
        "INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (employee["employee_id"],period["pay_period_id"],period["period_start"],f"TIME-{employee['employee_number']}-{period['period_start']}-PENDING",8.0,0.0,"anomaly_unapproved_time","submitted","pending","original"),
    )
    facts.append(_fact("TIME_UNAPPROVED", employee, period))

    # 4. Repeat an existing deduction linked to approved unpaid leave.
    deduction = dict(db.execute(
        "SELECT d.* FROM deductions d JOIN leave_records l ON l.leave_id=d.leave_id "
        "WHERE l.leave_type='unpaid' AND l.status='approved' ORDER BY d.deduction_id LIMIT 1"
    ).fetchone())
    deduction_seq += 1
    leave_employee = next(e for e in employees if e["employee_id"] == deduction["employee_id"])
    leave_period = dict(db.execute("SELECT * FROM pay_periods WHERE pay_period_id=?", (deduction["pay_period_id"],)).fetchone())
    db.execute(
        "INSERT INTO deductions(employee_id,pay_period_id,deduction_type,deduction_code,source_reference,leave_id,submission_type,amount,pre_tax,eligible,description) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (deduction["employee_id"],deduction["pay_period_id"],deduction["deduction_type"],f"DED-2026-{deduction_seq:07d}",deduction["source_reference"],deduction["leave_id"],"duplicate",deduction["amount"],deduction["pre_tax"],deduction["eligible"],deduction["description"]),
    )
    facts.append(_fact("DUP_UNPAID_LEAVE_DEDUCTION", leave_employee, leave_period))
    source_metadata.update(
        time_seq=time_seq,
        allowance_seq=allowance_seq,
        deduction_seq=deduction_seq,
        anomaly_record_counts={"time_entries": 2, "allowances": 1, "deductions": 1},
    )
    return facts


def inject_reconciliation_anomaly(db, source_metadata):
    """Alter one calculated result after its components were derived from source."""
    employees = [dict(row) for row in db.execute(
        "SELECT employee_id,employee_number,pay_group_id FROM employees ORDER BY employee_number"
    )]
    employee = employees[2]
    period = db.execute(
        "SELECT pay_period_id,pay_period_code FROM pay_periods WHERE pay_group_id=? AND pay_period_code='PP-2026-03'",
        (employee["pay_group_id"],),
    ).fetchone()
    period = dict(period)
    run = db.execute("SELECT payroll_run_id FROM payroll_runs WHERE pay_period_id=?", (period["pay_period_id"],)).fetchone()
    result = db.execute(
        "SELECT payroll_result_id,gross_pay,net_pay,calculation_details FROM payroll_results WHERE payroll_run_id=? AND employee_id=?",
        (run["payroll_run_id"],employee["employee_id"]),
    ).fetchone()
    import json
    details = json.loads(result["calculation_details"] or "{}")
    details["anomaly_label"] = "payroll_totals_fail_reconciliation"
    db.execute(
        "UPDATE payroll_results SET gross_pay=gross_pay+25,net_pay=net_pay+25,calculation_details=? WHERE payroll_result_id=?",
        (json.dumps(details,sort_keys=True),result["payroll_result_id"]),
    )
    return _fact("PAYROLL_RECONCILIATION", employee, period)


def build_ground_truth(facts):
    """Build expected validation outcomes without creating engine exceptions."""
    output = []
    rule_order={"HOURS_PERIOD_MAX":0,"DUPLICATE_ALLOWANCE":1,"TIME_UNAPPROVED":2,
                "DUP_UNPAID_LEAVE_DEDUCTION":3,"PAYROLL_RECONCILIATION":4}
    ordered=sorted(facts,key=lambda fact:(fact["pay_period_id"],rule_order[fact["issue_type"]]))
    for sequence, fact in enumerate(ordered, start=1):
        anomaly_id = f"PEX-2026-{sequence:06d}"
        rule_code, issue_type, decision = next(item for item in ANOMALY_RULES if item[0] == fact["issue_type"])
        output.append({
            "anomaly_id": anomaly_id,
            "employee_id": fact["employee_id"],
            "pay_period_id": fact["pay_period_id"],
            "issue_type": issue_type,
            "expected_validation_result": f"FAIL:{rule_code}",
            "expected_decision": decision,
        })
    return output


def write_ground_truth(rows, path):
    """Write independent anomaly expectations; never read by any validator."""
    import csv
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=GROUND_TRUTH_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_ground_truth_json(rows, path):
    """Write the same independent anomaly contract as a deterministic JSON array."""
    import json
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [{column: row[column] for column in GROUND_TRUTH_COLUMNS} for row in rows]
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fact(issue_type, employee, period):
    return {"issue_type": issue_type, "employee_db_id": employee["employee_id"],
            "employee_id": employee["employee_number"], "pay_period_id": period["pay_period_code"]}
