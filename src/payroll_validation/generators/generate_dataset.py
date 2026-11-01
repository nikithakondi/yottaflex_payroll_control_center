"""Generate deterministic YottaFlex payroll datasets (full scale by default)."""
import argparse
import csv
import json
from pathlib import Path

from openpyxl import Workbook

from payroll_validation.config import DATA_DIR, DATABASE_PATH, RANDOM_SEED, SYNTHETIC_EMPLOYEE_COUNT, TARGET_TRANSACTION_RECORDS
from payroll_validation.database.connection import connect
from payroll_validation.database.init_db import initialize, verify_database
from payroll_validation.generators.anomaly_generator import (
    build_ground_truth, inject_reconciliation_anomaly, inject_source_anomalies,
    write_ground_truth, write_ground_truth_json,
)
from payroll_validation.generators.master_data_generator import generate_master_data
from payroll_validation.generators.transaction_generator import PROFILES, generate_transactions
from payroll_validation.services.reconciliation_service import source_components, calculate_pay_components


def generate_dataset(profile="full", seed=RANDOM_SEED, database_path=None, output_dir=None, replace_existing=False):
    """Create one deterministic dataset profile, database and CSV snapshots.

    The full profile (3,000 employees) uses the normal application database
    path by default. Table snapshots are written under data/generated/full_current.
    Existing database rows are protected unless replace_existing=True.
    """
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {sorted(PROFILES)}")
    settings = PROFILES[profile]
    project_default = database_path is None and output_dir is None
    database_path = Path(database_path) if database_path else DATABASE_PATH
    snapshot_name = "full_current" if profile == "full" else "starter"
    output_dir = Path(output_dir) if output_dir else DATA_DIR / "generated" / snapshot_name
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    master = generate_master_data(settings["employees"], seed=seed, year=2026, month_count=3)
    initialize(database_path)
    with connect(database_path) as db:
        if db.execute("SELECT COUNT(*) FROM employees").fetchone()[0] and not replace_existing:
            raise FileExistsError(f"Refusing to replace existing payroll data in {database_path}; use replace_existing=True only for a disposable generated dataset")
        _clear_previous_generated_rows(db)
        group_ids = _insert_master_data(db, master)
        source_metadata = generate_transactions(db, profile=profile, seed=seed)
        source_anomalies = inject_source_anomalies(db, source_metadata)
        _build_payroll_inputs_and_results(db, seed=seed)
        recon_anomaly = inject_reconciliation_anomaly(db, source_metadata)
        ground_truth = build_ground_truth(source_anomalies + [recon_anomaly])

    validation_summary = None
    if profile == "full":
        from payroll_validation.validators.validation_service import validate_payroll_run

        with connect(database_path) as db:
            run_ids = [row[0] for row in db.execute(
                "SELECT payroll_run_id FROM payroll_runs ORDER BY payroll_run_id"
            )]
        reports = [validate_payroll_run(run_id, database_path, actor="synthetic_generator") for run_id in run_ids]
        category_counts = {}
        for report in reports:
            for category, count in report["exceptions_by_category"].items():
                category_counts[category] = category_counts.get(category, 0) + count
        validation_summary = {
            "payroll_runs_checked": len(reports),
            "records_checked": sum(report["records_checked"] for report in reports),
            "valid_records": sum(report["valid_records"] for report in reports),
            "invalid_records": sum(report["invalid_records"] for report in reports),
            "exceptions": sum(report["total_exceptions"] for report in reports),
            "export_ready": all(report["export_ready"] for report in reports),
            "exceptions_by_category": category_counts,
        }

    db_summary = verify_database(database_path)
    counts = _table_counts(database_path)
    transaction_count = sum(counts[name] for name in ("time_entries", "allowances", "deductions"))
    if counts["employees"] != settings["employees"]:
        raise RuntimeError(f"Expected {settings['employees']} employees, found {counts['employees']}")
    if len(ground_truth) != 5:
        raise RuntimeError(f"Expected five labeled anomalies, found {len(ground_truth)}")

    write_ground_truth(ground_truth, output_dir / "ground_truth.csv")
    write_ground_truth_json(ground_truth, output_dir / "ground_truth.json")
    if project_default:
        write_ground_truth(ground_truth, DATA_DIR / "ground_truth.csv")
        write_ground_truth_json(ground_truth, DATA_DIR / "ground_truth.json")
    _export_table_snapshots(database_path, output_dir)
    if profile == "full":
        _export_table_workbook(database_path, output_dir / "payroll_dataset.xlsx")
    manifest = {
        "profile": profile,
        "seed": seed,
        "employee_count": counts["employees"],
        "configured_employee_count": SYNTHETIC_EMPLOYEE_COUNT if profile == "full" else settings["employees"],
        "months": ["2026-01", "2026-02", "2026-03"],
        "period_count": counts["pay_periods"],
        "combined_transaction_count": transaction_count,
        "target_transaction_record_count": TARGET_TRANSACTION_RECORDS if profile == "full" else None,
        "transaction_record_count_definition": (
            "Final persisted time_entries + allowances + deductions rows. Includes approved, pending/rejected, "
            "corrected and duplicate submissions, plus planted source anomaly rows. Excludes leave_records, "
            "payroll inputs/results, audit events and ground_truth.csv."
        ),
        "transaction_counts": {name: counts[name] for name in ("time_entries", "allowances", "deductions")},
        "eligible_allowance_count": _eligible_count(database_path, "allowances"),
        "eligible_deduction_count": _eligible_count(database_path, "deductions"),
        "leave_correction_count": source_metadata["leave_correction_count"],
        "baseline_record_counts": {
            "time_entries": source_metadata["base_time_count"],
            "allowances": source_metadata["baseline_allowance_count"],
            "deductions": source_metadata["baseline_deduction_count"],
        },
        "revision_record_counts": {
            "time_entry_corrections": source_metadata["correction_count"],
            "time_entry_duplicates": source_metadata["duplicate_time_count"],
            "leave_corrections": source_metadata["leave_correction_count"],
        },
        "anomaly_record_counts": source_metadata.get("anomaly_record_counts", {}),
        "table_row_counts": counts,
        "anomaly_count": len(ground_truth),
        "anomaly_ids": [row["anomaly_id"] for row in ground_truth],
        "ground_truth_files": ["ground_truth.csv", "ground_truth.json"],
        "workbook_file": "payroll_dataset.xlsx" if profile == "full" else None,
        "validated_after_generation": validation_summary is not None,
        "validation_summary": validation_summary,
        "database_path": str(database_path),
        "output_dir": str(output_dir),
        "foreign_key_relationship_count": db_summary["foreign_key_count"],
        "integrity_check": db_summary["integrity"],
    }
    if profile == "full" and transaction_count != TARGET_TRANSACTION_RECORDS:
        raise RuntimeError(f"Full profile must persist exactly {TARGET_TRANSACTION_RECORDS:,} counted transaction rows; found {transaction_count}")
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _insert_master_data(db, master):
    db.executemany(
        "INSERT INTO pay_groups(code,name,pay_frequency,currency,standard_hours,overtime_multiplier,max_period_hours) VALUES (?,?,?,?,?,?,?)",
        [(r["code"],r["name"],r["pay_frequency"],r["currency"],r["standard_hours"],r["overtime_multiplier"],r["max_period_hours"]) for r in master["pay_groups"]],
    )
    group_ids = {r["code"]:r["pay_group_id"] for r in db.execute("SELECT pay_group_id,code FROM pay_groups")}
    department_names=sorted({r["department"] for r in master["employees"]})
    db.executemany("INSERT OR IGNORE INTO departments(department_name) VALUES (?)",[(name,) for name in department_names])
    department_ids={r["department_name"]:r["department_id"] for r in db.execute("SELECT department_id,department_name FROM departments")}
    db.executemany(
        "INSERT INTO employees(employee_number,first_name,last_name,email,department,department_id,job_title,hire_date,termination_date,pay_group_id,employment_status,standard_hours,annual_salary,hourly_rate,bank_account_token,tax_info_token) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["employee_number"],r["first_name"],r["last_name"],r["email"],r["department"],department_ids[r["department"]],r["job_title"],r["hire_date"],r["termination_date"],group_ids[r["pay_group_code"]],r["employment_status"],r["standard_hours"],r["annual_salary"],r["hourly_rate"],r["bank_account_token"],r["tax_info_token"]) for r in master["employees"]],
    )
    db.executemany(
        "INSERT INTO pay_periods(pay_group_id,period_start,period_end,payment_date,pay_period_code,status) VALUES (?,?,?,?,?,?)",
        [(group_ids[r["pay_group_code"]],r["period_start"],r["period_end"],r["payment_date"],r["pay_period_code"],r["status"]) for r in master["pay_periods"]],
    )
    return group_ids


def _build_payroll_inputs_and_results(db, seed):
    """Derive payroll inputs and results only from persisted source records."""
    periods = [dict(r) for r in db.execute("SELECT * FROM pay_periods ORDER BY period_start,pay_group_id")]
    for period in periods:
        db.execute(
            "INSERT INTO payroll_runs(pay_period_id,run_number,status,created_by) VALUES (?,1,'processed','synthetic_generator')",
            (period["pay_period_id"],),
        )
        run_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        group = db.execute("SELECT overtime_multiplier FROM pay_groups WHERE pay_group_id=?", (period["pay_group_id"],)).fetchone()
        employees = list(db.execute(
            "SELECT employee_id,employee_number,hourly_rate FROM employees WHERE pay_group_id=? AND employment_status='active' ORDER BY employee_number",
            (period["pay_group_id"],),
        ))
        for employee in employees:
            source = source_components(db, employee["employee_id"], period["pay_period_id"])
            regular_hours, overtime_hours = source["regular_hours"], source["overtime_hours"]
            paid_leave_hours = source["paid_leave_hours"]
            allowance_total, deduction_total = float(source["allowance_total"]), float(source["deduction_total"])
            calculated = calculate_pay_components(source, employee["hourly_rate"], group["overtime_multiplier"])
            input_code = f"PIN-{employee['employee_number']}-{period['pay_period_code'][3:]}"
            db.execute(
                "INSERT INTO payroll_inputs(payroll_input_code,employee_id,pay_period_id,regular_hours,overtime_hours,paid_leave_hours,allowance_total,deduction_total) VALUES (?,?,?,?,?,?,?,?)",
                (input_code,employee["employee_id"],period["pay_period_id"],regular_hours,overtime_hours,paid_leave_hours,allowance_total,deduction_total),
            )
            db.execute(
                "INSERT INTO payroll_run_inputs(payroll_run_id,employee_id,pay_period_id,regular_hours,overtime_hours,paid_leave_hours,allowance_total,deduction_total) VALUES (?,?,?,?,?,?,?,?)",
                (run_id,employee["employee_id"],period["pay_period_id"],regular_hours,overtime_hours,paid_leave_hours,allowance_total,deduction_total),
            )
            payroll_run_input_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            regular_pay = float(calculated["regular_pay"])
            overtime_pay = float(calculated["overtime_pay"])
            gross_pay = float(calculated["gross_pay"])
            net_pay = float(calculated["net_pay"])
            if net_pay < 0:
                raise ValueError(f"Generated deductions exceed gross pay for {input_code}")
            details = json.dumps({"hourly_rate":float(employee["hourly_rate"]),"paid_leave_hours":paid_leave_hours,"source":"source_records"},sort_keys=True)
            db.execute(
                "INSERT INTO payroll_results(payroll_run_input_id,payroll_run_id,employee_id,regular_hours,overtime_hours,regular_pay,overtime_pay,allowance_total,deduction_total,gross_pay,net_pay,calculation_details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (payroll_run_input_id,run_id,employee["employee_id"],regular_hours,overtime_hours,regular_pay,overtime_pay,allowance_total,deduction_total,gross_pay,net_pay,details),
            )


def _clear_previous_generated_rows(db):
    """Replace a previous generated snapshot in this dataset-specific DB."""
    count = db.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if count:
        non_synthetic = db.execute("SELECT COUNT(*) FROM employees WHERE employee_number NOT LIKE 'EMP-%'").fetchone()[0]
        if non_synthetic:
            raise RuntimeError("Refusing to replace a database containing non-synthetic employee records")
    for table in ("approval_history","exception_assignments","exception_review_history","audit_events","payroll_exports","approvals","exceptions","payroll_results","payroll_run_inputs","payroll_inputs","payroll_runs","employee_pay_group_assignments"):
        if table == "audit_events":
            # Explicit regeneration of a disposable synthetic snapshot resets
            # its history along with the data. Keep the append-only trigger in
            # place for all normal application operations.
            db.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_delete")
        db.execute(f'DELETE FROM "{table}"')
        if table == "audit_events":
            db.execute("""
                CREATE TRIGGER trg_audit_events_no_delete BEFORE DELETE ON audit_events
                BEGIN SELECT RAISE(ABORT,'audit events are append-only'); END;
            """)
    _delete_correction_chains(db,"deductions","deduction_id","supersedes_deduction_id")
    _delete_correction_chains(db,"allowances","allowance_id","supersedes_allowance_id")
    _delete_correction_chains(db,"leave_records","leave_id","supersedes_leave_id")
    # Remove self-referencing revision rows before their originals.
    db.execute("DELETE FROM time_entries WHERE supersedes_time_entry_id IS NOT NULL")
    db.execute("DELETE FROM time_entries")
    for table in ("leave_records","pay_periods","employees","departments","pay_groups"):
        db.execute(f'DELETE FROM "{table}"')


def _delete_correction_chains(db, table, key, parent):
    """Delete terminal correction rows first, preserving self-FK integrity."""
    while True:
        cursor=db.execute(f"DELETE FROM {table} WHERE NOT EXISTS (SELECT 1 FROM {table} child WHERE child.{parent}={table}.{key})")
        if cursor.rowcount == 0: break


def _table_counts(path):
    names = ("pay_groups","departments","employees","employee_pay_group_assignments","pay_periods","time_entries","leave_records","allowances","deductions","payroll_inputs","payroll_run_inputs","payroll_runs","payroll_results","validation_rules","exceptions","approvals","approval_history","exception_assignments","exception_review_history","payroll_exports","audit_events")
    with connect(path) as db:
        return {name:int(db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in names}


def _eligible_count(path, table):
    if table not in {"allowances", "deductions"}:
        raise ValueError(f"Unsupported eligible transaction table: {table}")
    with connect(path) as db:
        return int(db.execute(f"SELECT COUNT(*) FROM {table} WHERE eligible=1").fetchone()[0])


def _export_table_snapshots(database_path, output_dir):
    with connect(database_path) as db:
        for table in ("pay_groups","departments","employees","employee_pay_group_assignments","pay_periods","validation_rules","time_entries","leave_records","allowances","deductions","payroll_inputs","payroll_run_inputs","payroll_runs","payroll_results","exceptions","approval_history","exception_assignments","exception_review_history","approvals","payroll_exports","audit_events"):
            cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY 1')
            with (output_dir / f"{table}.csv").open("w", newline="", encoding="utf-8") as output:
                writer = csv.writer(output)
                writer.writerow([column[0] for column in cursor.description])
                while rows := cursor.fetchmany(5_000):
                    writer.writerows(tuple(row) for row in rows)


def _export_table_workbook(database_path, workbook_path):
    """Write all database tables to one streaming, multi-sheet Excel workbook."""
    workbook = Workbook(write_only=True)
    with connect(database_path) as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        for table in tables:
            sheet = workbook.create_sheet(title=table[:31])
            cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY 1')
            sheet.append([column[0] for column in cursor.description])
            while rows := cursor.fetchmany(5_000):
                for row in rows:
                    sheet.append(tuple(row))
    workbook.save(workbook_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="full")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--replace-existing", action="store_true",help="Replace data in an existing generated database (destructive; use only for a disposable snapshot)")
    args = parser.parse_args()
    result = generate_dataset(args.profile,args.seed,args.database,args.output_dir,args.replace_existing)
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
