"""Write current validation, reconciliation, and exception report snapshots."""
import argparse
import csv
from pathlib import Path

from payroll_validation.config import DATABASE_PATH, PROJECT_ROOT
from payroll_validation.database.connection import connect
from payroll_validation.exports.report_exports import (
    reconciliation_report_rows,
    validation_report_rows,
)


def write_reports(database_path=DATABASE_PATH, output_dir=None):
    """Generate CSV report snapshots from the selected database (default: app DB)."""
    output_dir = Path(output_dir or PROJECT_ROOT / "reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as db:
        run_ids = [row[0] for row in db.execute(
            "SELECT payroll_run_id FROM payroll_runs ORDER BY payroll_run_id"
        )]
        rows_by_file = {
            "validation_report.csv": [row for run_id in run_ids for row in validation_report_rows(run_id, database_path)],
            "reconciliation_report.csv": [row for run_id in run_ids for row in reconciliation_report_rows(run_id, database_path)],
            "exception_report.csv": [dict(row) for row in db.execute(
                "SELECT exception_code AS exception_id, employee_reference AS employee_id, "
                "pay_period_reference AS pay_period_id, rule_code AS issue_type, severity, "
                "workflow_status AS status, message, detected_at FROM exceptions ORDER BY exception_id"
            )],
        }
    counts = {}
    for filename, rows in rows_by_file.items():
        path = output_dir / filename
        if rows:
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        else:
            path.write_text("", encoding="utf-8")
        counts[filename] = len(rows)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports")
    arguments = parser.parse_args()
    for filename, count in write_reports(arguments.database, arguments.output_dir).items():
        print(f"{filename}: {count} rows")
