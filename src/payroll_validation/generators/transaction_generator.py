"""Generate reproducible time, leave, allowance and deduction source records."""
import calendar
import random
from datetime import date, timedelta

from payroll_validation.config import RANDOM_SEED, SYNTHETIC_EMPLOYEE_COUNT

PROFILES = {
    "starter": {"employees": 100, "time_entries_per_period": 2, "allowances": 200, "deductions": 200},
    # 99,456 baseline rows plus 540 time revisions and four source anomalies
    # produces exactly 100,000 final time + allowance + deduction records.
    "full": {"employees": SYNTHETIC_EMPLOYEE_COUNT, "time_entries_per_period": 4, "allowances": 31_728, "deductions": 31_728},
}
ALLOWANCE_TYPES = ("commute", "meal", "home_office", "shift")
DEDUCTION_TYPES = ("tax_withholding", "retirement", "health_insurance", "union_dues", "student_loan")


def generate_transactions(db, profile="starter", seed=RANDOM_SEED):
    """Write baseline transactions and revision history; return deterministic counters."""
    if profile not in PROFILES:
        raise ValueError(f"Unknown dataset profile: {profile}")
    settings = PROFILES[profile]
    rng = random.Random(seed + 100)
    employees = [dict(row) for row in db.execute(
        "SELECT employee_id, employee_number, pay_group_id, hourly_rate FROM employees ORDER BY employee_number"
    )]
    periods = {
        (row["pay_group_id"], row["pay_period_code"]): row["pay_period_id"]
        for row in db.execute("SELECT pay_period_id,pay_group_id,pay_period_code FROM pay_periods")
    }
    employee_periods = []
    time_rows = []
    time_seq = 0
    for employee in employees:
        group_periods = [
            (code, period_id) for (group_id, code), period_id in periods.items()
            if group_id == employee["pay_group_id"]
        ]
        for period_code, period_id in sorted(group_periods):
            employee_periods.append((employee, period_code, period_id))
            start, end = _period_dates(db, period_id)
            dates = _weekly_dates(start, end)
            selected_dates = dates[:settings["time_entries_per_period"]]
            if len(selected_dates) < settings["time_entries_per_period"]:
                selected_dates.extend(_weekdays_not_in(start, end, selected_dates)[:settings["time_entries_per_period"] - len(selected_dates)])
            for work_date in selected_dates:
                time_seq += 1
                overtime = rng.choice((0.0, 0.0, 0.0, 1.0, 2.0, 3.0))
                time_rows.append({
                    "employee_id": employee["employee_id"], "pay_period_id": period_id,
                    "work_date": work_date.isoformat(), "time_entry_code": _time_code(employee["employee_number"], work_date.isoformat()),
                    "regular_hours": 40.0, "overtime_hours": overtime, "source": "synthetic_weekly_timesheet",
                    "status": "approved", "approval_status": "approved", "submission_type": "original",
                    "supersedes_time_entry_id": None,
                })
    _insert_time_rows(db, time_rows)
    base_time_count = len(time_rows)

    leave_rows = _generate_leave_rows(db, employee_periods, rng)
    db.executemany(
        "INSERT INTO leave_records(employee_id,pay_period_id,leave_type,start_date,end_date,hours,status,supersedes_leave_id) VALUES (?,?,?,?,?,?,?,NULL)",
        [(r["employee_id"],r["pay_period_id"],r["leave_type"],r["start_date"],r["end_date"],r["hours"],r["status"]) for r in leave_rows],
    )
    leave_correction_count = _insert_leave_correction(db)
    unpaid_leaves = list(db.execute(
        "SELECT l.leave_id,l.employee_id,l.pay_period_id,l.hours,e.hourly_rate,e.employee_number,p.pay_period_code "
        "FROM leave_records l JOIN employees e USING(employee_id) JOIN pay_periods p USING(pay_period_id) "
        "WHERE l.leave_type='unpaid' AND l.status='approved' ORDER BY l.leave_id"
    ))

    allowance_rows, duplicate_allowance_source = _generate_allowances(employee_periods, settings["allowances"], rng)
    db.executemany(
        "INSERT INTO allowances(employee_id,pay_period_id,allowance_type,allowance_code,source_reference,submission_type,amount,taxable,eligible,description) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(r["employee_id"],r["pay_period_id"],r["allowance_type"],r["allowance_code"],r["source_reference"],r["submission_type"],r["amount"],r["taxable"],r["eligible"],r["description"]) for r in allowance_rows],
    )
    deduction_rows, duplicate_leave_source = _generate_deductions(employee_periods, unpaid_leaves, settings["deductions"], rng)
    db.executemany(
        "INSERT INTO deductions(employee_id,pay_period_id,deduction_type,deduction_code,source_reference,leave_id,submission_type,amount,pre_tax,eligible,description) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(r["employee_id"],r["pay_period_id"],r["deduction_type"],r["deduction_code"],r["source_reference"],r["leave_id"],r["submission_type"],r["amount"],r["pre_tax"],r["eligible"],r["description"]) for r in deduction_rows],
    )

    correction_count, duplicate_time_count = _insert_time_revision_history(db, base_time_count)
    return {
        "employee_periods": employee_periods,
        "base_time_count": base_time_count,
        "time_seq": time_seq + correction_count + duplicate_time_count,
        "allowance_seq": len(allowance_rows),
        "deduction_seq": len(deduction_rows),
        "correction_count": correction_count,
        "duplicate_time_count": duplicate_time_count,
        "duplicate_allowance_source": duplicate_allowance_source,
        "duplicate_leave_source": duplicate_leave_source,
        "approved_unpaid_leave_count": len(unpaid_leaves),
        "leave_correction_count": leave_correction_count,
        "baseline_allowance_count": len(allowance_rows),
        "baseline_deduction_count": len(deduction_rows),
    }


def _generate_leave_rows(db, employee_periods, rng):
    records = []
    for index, (employee, _, period_id) in enumerate(employee_periods):
        start, end = _period_dates(db, period_id)
        workdays = _weekdays_not_in(start, end, _weekly_dates(start, end))
        if not workdays:
            continue
        # Lifecycle values are deterministic by employee-period sequence; the
        # seed affects date selection only, never payroll status decisions.
        # Guarantee approved unpaid and approved paid examples.
        if index == 0 or index % 29 == 0:
            leave_type = "unpaid"
            status = "approved"
        elif index == 5 or index % 7 == 0:
            leave_type = "paid"
            status = "approved"
        elif index % 11 == 0:
            leave_type = "paid"
            status = "pending"
        else:
            continue
        leave_date = rng.choice(workdays)
        records.append({"employee_id":employee["employee_id"],"pay_period_id":period_id,
                        "leave_type":leave_type,"start_date":leave_date.isoformat(),
                        "end_date":leave_date.isoformat(),"hours":8.0,"status":status})
    return records


def _insert_leave_correction(db):
    """Append one approved paid-leave correction while retaining its original."""
    original = db.execute(
        "SELECT leave_id,employee_id,pay_period_id,start_date,end_date,hours FROM leave_records "
        "WHERE leave_type='paid' AND status='approved' ORDER BY leave_id LIMIT 1"
    ).fetchone()
    if original is None:
        raise ValueError("At least one approved paid leave is required for correction history")
    corrected_hours = round(float(original["hours"]) / 2, 2)
    db.execute(
        "INSERT INTO leave_records(employee_id,pay_period_id,leave_type,start_date,end_date,hours,status,supersedes_leave_id) "
        "VALUES (?,?, 'paid',?,?,?,'approved',?)",
        (original["employee_id"], original["pay_period_id"], original["start_date"],
         original["end_date"], corrected_hours, original["leave_id"]),
    )
    return 1


def _generate_allowances(employee_periods, target_count, rng):
    candidates = []
    for employee, period_code, period_id in employee_periods:
        for allowance_type in ALLOWANCE_TYPES:
            candidates.append((employee, period_code, period_id, allowance_type))
    if target_count > len(candidates):
        raise ValueError("Allowance target exceeds available distinct employee-period-type combinations")
    rng.shuffle(candidates)
    baseline = candidates[:target_count]
    rows = []
    duplicate_source = None
    for seq, (employee, period_code, period_id, allowance_type) in enumerate(baseline, start=1):
        source = f"ALW-SRC-{employee['employee_number']}-{period_code}-{allowance_type}"
        row = {"employee_id":employee["employee_id"],"pay_period_id":period_id,
               "allowance_type":allowance_type,"allowance_code":f"ALW-2026-{seq:07d}",
               "source_reference":source,"submission_type":"original",
               "amount":round(rng.uniform(25, 225), 2),"taxable":int(allowance_type != "home_office"),
               "eligible":int(not (allowance_type == "home_office" and employee["employee_id"] % 4 == 0)),
               "description":f"Synthetic {allowance_type.replace('_',' ')} allowance"}
        rows.append(row)
        if duplicate_source is None:
            duplicate_source = row
    return rows, duplicate_source


def _generate_deductions(employee_periods, unpaid_leaves, target_count, rng):
    rows = []
    seq = 0
    for leave in unpaid_leaves:
        seq += 1
        amount = round(float(leave["hourly_rate"]) * float(leave["hours"]), 2)
        rows.append({"employee_id":leave["employee_id"],"pay_period_id":leave["pay_period_id"],
                     "deduction_type":"unpaid_leave","deduction_code":f"DED-2026-{seq:07d}",
                     "source_reference":f"DED-LEAVE-{leave['leave_id']}","leave_id":leave["leave_id"],
                     "submission_type":"original","amount":amount,"pre_tax":0,
                     "eligible":1,
                     "description":"Approved unpaid leave"})
    if len(rows) >= target_count:
        raise ValueError("Unpaid-leave deduction count exceeds configured deduction target")

    candidates = []
    for employee, period_code, period_id in employee_periods:
        for deduction_type in DEDUCTION_TYPES:
            candidates.append((employee, period_code, period_id, deduction_type))
    rng.shuffle(candidates)
    needed = target_count - len(rows)
    if needed > len(candidates):
        raise ValueError("Deduction target exceeds available distinct employee-period-type combinations")
    for employee, period_code, period_id, deduction_type in candidates[:needed]:
        gross_estimate = float(employee["hourly_rate"]) * 160
        if deduction_type == "tax_withholding":
            amount = gross_estimate * rng.uniform(0.08, 0.14)
        elif deduction_type == "retirement":
            amount = gross_estimate * rng.uniform(0.03, 0.06)
        elif deduction_type == "health_insurance":
            amount = rng.uniform(65, 180)
        elif deduction_type == "union_dues":
            amount = rng.uniform(15, 45)
        else:
            amount = rng.uniform(25, 110)
        seq += 1
        rows.append({"employee_id":employee["employee_id"],"pay_period_id":period_id,
                     "deduction_type":deduction_type,"deduction_code":f"DED-2026-{seq:07d}",
                     "source_reference":f"DED-SRC-{employee['employee_number']}-{period_code}-{deduction_type}",
                     "leave_id":None,"submission_type":"original","amount":round(amount,2),
                     "pre_tax":int(deduction_type == "retirement"),
                     "eligible":int(not (deduction_type == "student_loan" and employee["employee_id"] % 3 != 0)),
                     "description":f"Synthetic {deduction_type.replace('_',' ')} deduction"})
    leave_source = next((r for r in rows if r["leave_id"] is not None), None)
    if leave_source is None:
        raise ValueError("At least one approved unpaid leave deduction is required")
    return rows, leave_source


def _insert_time_rows(db, rows):
    db.executemany(
        "INSERT INTO time_entries(employee_id,pay_period_id,work_date,time_entry_code,regular_hours,overtime_hours,source,status,approval_status,submission_type,supersedes_time_entry_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(r["employee_id"],r["pay_period_id"],r["work_date"],r["time_entry_code"],r["regular_hours"],r["overtime_hours"],r["source"],r["status"],r["approval_status"],r["submission_type"],r["supersedes_time_entry_id"]) for r in rows],
    )


def _insert_time_revision_history(db, base_time_count):
    base_rows = [dict(row) for row in db.execute(
        "SELECT t.*,e.employee_number FROM time_entries t JOIN employees e USING(employee_id) WHERE t.submission_type='original' ORDER BY t.time_entry_id"
    )]
    correction_count = max(1, round(base_time_count * 0.01))
    duplicate_count = max(1, round(base_time_count * 0.005))
    corrected_rows = base_rows[:correction_count]
    duplicate_rows = base_rows[correction_count:correction_count + duplicate_count]
    if not duplicate_rows:
        duplicate_rows = base_rows[-1:]
        duplicate_count = len(duplicate_rows)

    corrections, duplicates = [], []
    seq = base_time_count
    for row in corrected_rows:
        db.execute("UPDATE time_entries SET status='rejected',approval_status='rejected' WHERE time_entry_id=?", (row["time_entry_id"],))
        seq += 1
        corrections.append({**row,"time_entry_code":_time_code(row["employee_number"],row["work_date"],"CORR",seq),"regular_hours":max(0.0,row["regular_hours"]-0.5),
                            "source":"synthetic_corrected_timesheet","status":"approved","approval_status":"approved",
                            "submission_type":"correction","supersedes_time_entry_id":row["time_entry_id"]})
    for row in duplicate_rows:
        seq += 1
        duplicates.append({**row,"time_entry_code":_time_code(row["employee_number"],row["work_date"],"DUP",seq),"source":"synthetic_duplicate_submission",
                           "status":"rejected","approval_status":"rejected","submission_type":"duplicate",
                           "supersedes_time_entry_id":row["time_entry_id"]})
    _insert_time_rows(db, corrections + duplicates)
    return len(corrections), len(duplicates)


def _time_code(employee_number, work_date, revision=None, sequence=None):
    base=f"TIME-{employee_number}-{work_date}"
    return f"{base}-{revision}-{sequence:05d}" if revision else base


def _period_dates(db, period_id):
    row = db.execute("SELECT period_start,period_end FROM pay_periods WHERE pay_period_id=?", (period_id,)).fetchone()
    return date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"])


def _weekly_dates(start, end):
    first_friday = start + timedelta(days=(4 - start.weekday()) % 7)
    values = []
    day = first_friday
    while day <= end:
        values.append(day)
        day += timedelta(days=7)
    return values


def _weekdays_not_in(start, end, excluded):
    excluded = set(excluded)
    values, day = [], start
    while day <= end:
        if day.weekday() < 5 and day not in excluded:
            values.append(day)
        day += timedelta(days=1)
    return values
