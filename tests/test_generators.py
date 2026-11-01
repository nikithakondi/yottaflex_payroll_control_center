import csv
import pytest
from payroll_validation.database.connection import connect
from payroll_validation.generators.generate_dataset import generate_dataset
from payroll_validation.generators.master_data_generator import generate_master_data
from payroll_validation.generators.transaction_generator import PROFILES


def test_starter_dataset_has_required_volume_entities_and_ids(tmp_path):
    db_path = tmp_path / "starter.db"
    output_dir = tmp_path / "starter"
    manifest = generate_dataset("starter", database_path=db_path, output_dir=output_dir)

    assert manifest["seed"] == 20261022
    assert manifest["employee_count"] == 100
    assert manifest["period_count"] == 3
    assert 950 <= manifest["combined_transaction_count"] <= 1_100
    assert manifest["integrity_check"] == "ok"

    with connect(db_path) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not list(db.execute("PRAGMA foreign_key_check"))
        assert db.execute("SELECT COUNT(*) FROM departments").fetchone()[0] >= 5
        assert db.execute("SELECT COUNT(*) FROM employees WHERE department_id IS NULL").fetchone()[0] == 0
        assert db.execute("SELECT employee_number FROM employees ORDER BY employee_id LIMIT 1").fetchone()[0] == "EMP-000001"
        assert {r[0] for r in db.execute("SELECT pay_period_code FROM pay_periods")} == {"PP-2026-01", "PP-2026-02", "PP-2026-03"}
        assert db.execute("SELECT COUNT(*) FROM time_entries WHERE time_entry_code NOT LIKE 'TIME-EMP-%-2026-%'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM payroll_inputs").fetchone()[0] == 300
        assert db.execute("SELECT COUNT(*) FROM payroll_run_inputs").fetchone()[0] == 300
        assert db.execute("SELECT COUNT(*) FROM payroll_results").fetchone()[0] == 300
        assert db.execute("SELECT COUNT(*) FROM time_entries WHERE approval_status='approved'").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM time_entries WHERE approval_status='pending'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM time_entries WHERE submission_type='correction'").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM time_entries WHERE submission_type='duplicate'").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM leave_records WHERE leave_type='paid' AND status='approved'").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM leave_records WHERE leave_type='unpaid' AND status='approved'").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM leave_records WHERE supersedes_leave_id IS NOT NULL").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM allowances WHERE submission_type='duplicate'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM allowances WHERE eligible=0").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM deductions WHERE eligible=0").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM deductions WHERE submission_type='duplicate' AND leave_id IS NOT NULL").fetchone()[0] == 1
        # Anomalies belong in ground truth only; the validation engine creates exceptions.
        assert db.execute("SELECT COUNT(*) FROM exceptions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM payroll_inputs WHERE payroll_input_code LIKE 'PIN-EMP-%-2026-%'").fetchone()[0] == 300

        input_row = db.execute(
            "SELECT pi.regular_hours AS input_regular_hours,pi.overtime_hours AS input_overtime_hours,"
            "pi.allowance_total AS input_allowance_total,pi.deduction_total AS input_deduction_total,"
            "e.hourly_rate,pr.regular_pay,pr.overtime_pay,pr.allowance_total AS result_allowance_total,"
            "pr.deduction_total AS result_deduction_total,pr.gross_pay,pr.net_pay "
            "FROM payroll_inputs pi JOIN employees e USING(employee_id) "
            "JOIN payroll_runs r USING(pay_period_id) JOIN payroll_results pr ON pr.payroll_run_id=r.payroll_run_id AND pr.employee_id=pi.employee_id "
            "WHERE NOT EXISTS (SELECT 1 FROM exceptions x WHERE x.rule_code='PAYROLL_RECONCILIATION' AND x.employee_id=pi.employee_id AND x.payroll_run_id=r.payroll_run_id) LIMIT 1"
        ).fetchone()
        assert round(input_row["input_allowance_total"], 2) == input_row["result_allowance_total"]
        assert round(input_row["input_deduction_total"], 2) == input_row["result_deduction_total"]
        assert round(input_row["regular_pay"] + input_row["overtime_pay"] + input_row["result_allowance_total"], 2) == input_row["gross_pay"]
        assert round(input_row["gross_pay"] - input_row["result_deduction_total"], 2) == input_row["net_pay"]

    with (output_dir / "ground_truth.csv").open(encoding="utf-8", newline="") as source:
        ground_truth = list(csv.DictReader(source))
    assert len(ground_truth) == 5
    assert {row["issue_type"] for row in ground_truth} == {
        "Hours exceeding the pay-period maximum", "Duplicate allowance submissions",
        "Unapproved time entries", "Duplicate unpaid leave deductions",
        "Payroll totals failing reconciliation",
    }
    assert (output_dir / "employees.csv").exists()
    assert (output_dir / "time_entries.csv").exists()
    assert (output_dir / "ground_truth.csv").exists()
    assert (output_dir / "ground_truth.json").exists()
    assert (output_dir / "manifest.json").exists()
    with pytest.raises(FileExistsError,match="Refusing to replace"):
        generate_dataset("starter",database_path=db_path,output_dir=output_dir)
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM employees").fetchone()[0]==100
        db.execute("INSERT INTO audit_events(entity_type,entity_id,action,actor) VALUES ('test','old','old_snapshot','pytest')")
    generate_dataset("starter",database_path=db_path,output_dir=output_dir,replace_existing=True)
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM employees").fetchone()[0]==100
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]==0


def test_generator_profiles_define_starter_and_full_scale():
    assert PROFILES["starter"]["employees"] == 100
    assert PROFILES["full"]["employees"] == 3_000
    baseline = 3_000 * 3 * PROFILES["full"]["time_entries_per_period"] + PROFILES["full"]["allowances"] + PROFILES["full"]["deductions"]
    time_revisions = round(36_000 * 0.01) + round(36_000 * 0.005)
    source_anomalies = 4
    assert baseline == 99_456
    assert baseline + time_revisions + source_anomalies == 100_000
    assert len(generate_master_data()["employees"]) == 3_000


def test_master_data_is_deterministic_and_realistic():
    first = generate_master_data(100, seed=20261022)
    second = generate_master_data(100, seed=20261022)
    assert first == second
    assert len(first["employees"]) == 100
    assert {row["pay_group_code"] for row in first["employees"]} == {"PG-MONTHLY-01"}
    assert all(28_000 <= row["annual_salary"] <= 220_000 for row in first["employees"])
    assert all(len(row["bank_account_token"]) >= 15 and row["bank_account_token"][:2].isalpha() for row in first["employees"])
    assert all(row["tax_info_token"].startswith("TAX-") for row in first["employees"])


def test_starter_generation_is_reproducible_for_fixed_seed(tmp_path):
    first=generate_dataset("starter",seed=20261022,database_path=tmp_path/"a.db",output_dir=tmp_path/"a")
    second=generate_dataset("starter",seed=20261022,database_path=tmp_path/"b.db",output_dir=tmp_path/"b")
    assert first["combined_transaction_count"]==second["combined_transaction_count"]
    for table in ("employees","pay_periods","time_entries","leave_records","allowances","deductions","payroll_inputs","payroll_results"):
        with connect(tmp_path/"a.db") as left, connect(tmp_path/"b.db") as right:
            columns=[r[1] for r in left.execute(f'PRAGMA table_info("{table}")') if r[1] not in {"created_at","detected_at","last_detected_at"}]
            projection=",".join(columns)
            assert [tuple(r) for r in left.execute(f"SELECT {projection} FROM {table} ORDER BY 1")] == [tuple(r) for r in right.execute(f"SELECT {projection} FROM {table} ORDER BY 1")]
    assert (tmp_path/"a"/"ground_truth.csv").read_bytes()==(tmp_path/"b"/"ground_truth.csv").read_bytes()
