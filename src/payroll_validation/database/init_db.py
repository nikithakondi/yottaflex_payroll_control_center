"""Initialize and verify the local SQLite payroll database."""
from pathlib import Path

from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect

REQUIRED_TABLES = {
    "pay_groups", "departments", "employees", "pay_periods", "time_entries", "leave_records",
    "allowances", "deductions", "payroll_runs", "payroll_results", "payroll_inputs", "payroll_run_inputs", "exceptions",
    "validation_rules", "approvals", "approval_history", "exception_assignments", "exception_review_history", "payroll_exports", "audit_events",
    "employee_pay_group_assignments",
}

PRIMARY_KEYS = {
    "pay_groups":"pay_group_id", "departments":"department_id", "employees":"employee_id",
    "employee_pay_group_assignments":"assignment_id", "pay_periods":"pay_period_id",
    "validation_rules":"validation_rule_id", "time_entries":"time_entry_id",
    "leave_records":"leave_id", "allowances":"allowance_id", "deductions":"deduction_id",
    "payroll_runs":"payroll_run_id", "payroll_results":"payroll_result_id",
    "payroll_inputs":"payroll_input_id", "payroll_run_inputs":"payroll_run_input_id",
    "exceptions":"exception_id", "approvals":"approval_id", "approval_history":"approval_id",
    "exception_assignments":"assignment_id", "exception_review_history":"review_action_id",
    "payroll_exports":"export_id", "audit_events":"audit_event_id",
}


def verify_database(path=DATABASE_PATH, allow_fk_violations=False):
    """Check required tables, enabled foreign keys, FK declarations and integrity."""
    with connect(path) as db:
        if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("SQLite foreign-key enforcement is disabled")

        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(f"Database is missing required tables: {sorted(missing)}")

        foreign_keys = {}
        for table in sorted(REQUIRED_TABLES):
            foreign_keys[table] = [dict(row) for row in db.execute(f'PRAGMA foreign_key_list("{table}")')]
        if not any(foreign_keys.values()):
            raise RuntimeError("No foreign-key relationships were found")

        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        violations = list(db.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or (violations and not allow_fk_violations):
            raise RuntimeError(f"Database integrity check failed: {integrity}; FK violations: {violations}")

        result_link_errors = db.execute(
            "SELECT COUNT(*) FROM payroll_results pr WHERE pr.payroll_run_input_id IS NULL OR NOT EXISTS ("
            "SELECT 1 FROM payroll_run_inputs ri WHERE ri.payroll_run_input_id=pr.payroll_run_input_id "
            "AND ri.payroll_run_id=pr.payroll_run_id AND ri.employee_id=pr.employee_id)"
        ).fetchone()[0]
        run_period_errors = db.execute(
            "SELECT COUNT(*) FROM payroll_run_inputs ri JOIN payroll_runs r USING(payroll_run_id) "
            "WHERE ri.pay_period_id<>r.pay_period_id"
        ).fetchone()[0]
        assignment_gaps = db.execute(
            "SELECT COUNT(*) FROM employees e WHERE NOT EXISTS (SELECT 1 FROM employee_pay_group_assignments a "
            "WHERE a.employee_id=e.employee_id AND a.pay_group_id=e.pay_group_id AND a.status<>'cancelled' "
            "AND a.effective_from<=COALESCE(e.termination_date,'9999-12-31') "
            "AND (a.effective_to IS NULL OR a.effective_to>e.hire_date))"
        ).fetchone()[0]
        if result_link_errors or run_period_errors or assignment_gaps:
            raise RuntimeError(
                "Payroll relationship integrity failed: "
                f"unlinked results={result_link_errors}, run-period mismatches={run_period_errors}, "
                f"employee assignment gaps={assignment_gaps}"
            )

        indexes = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        }
        return {
            "tables": sorted(REQUIRED_TABLES),
            "table_count": len(REQUIRED_TABLES),
            "foreign_key_count": sum(map(len, foreign_keys.values())),
            "foreign_keys_by_table": foreign_keys,
            "index_count": len(indexes),
            "integrity": integrity,
            "linked_payroll_results": db.execute("SELECT COUNT(*) FROM payroll_results").fetchone()[0] - result_link_errors,
            "employee_pay_group_assignments": db.execute("SELECT COUNT(*) FROM employee_pay_group_assignments").fetchone()[0],
            "relationship_errors": 0,
        }


def initialize(path=DATABASE_PATH, allow_fk_violations=False):
    """Create all schema objects if needed, then return a verification summary."""
    path = Path(path)
    schema_path = Path(__file__).with_name("schema.sql")
    schema = schema_path.read_text(encoding="utf-8")
    with connect(path) as db:
        db.executescript(f"BEGIN IMMEDIATE;\n{schema}\nCOMMIT;")
        _apply_additive_columns(db)
        _ensure_relational_constraints(db)
        db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department_id);
            CREATE INDEX IF NOT EXISTS idx_time_supersedes ON time_entries(supersedes_time_entry_id);
            CREATE INDEX IF NOT EXISTS idx_leave_supersedes ON leave_records(supersedes_leave_id);
            CREATE INDEX IF NOT EXISTS idx_allowance_supersedes ON allowances(supersedes_allowance_id);
            CREATE INDEX IF NOT EXISTS idx_deduction_supersedes ON deductions(supersedes_deduction_id);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_pay_period_group_code ON pay_periods(pay_group_id, pay_period_code);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_time_entry_code ON time_entries(time_entry_code);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_allowance_code ON allowances(allowance_code);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_deduction_code ON deductions(deduction_code);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_exception_code ON exceptions(exception_code);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_exception_finding_key ON exceptions(finding_key);
            CREATE INDEX IF NOT EXISTS idx_exceptions_period_rule ON exceptions(pay_period_id, rule_code, status);
            CREATE INDEX IF NOT EXISTS idx_employee_group_assignment_effective ON employee_pay_group_assignments(employee_id,effective_from,effective_to);
            CREATE INDEX IF NOT EXISTS idx_group_assignment_effective ON employee_pay_group_assignments(pay_group_id,effective_from,effective_to);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_results_run_input ON payroll_results(payroll_run_input_id) WHERE payroll_run_input_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_exports_one_per_run ON payroll_exports(payroll_run_id);
        """)
    return verify_database(path,allow_fk_violations=allow_fk_violations)


def _apply_additive_columns(db):
    """Add generator metadata to existing databases without rebuilding tables."""
    additions = {
        "pay_groups": {
            "max_period_hours": "REAL NOT NULL DEFAULT 200 CHECK (max_period_hours > 0)",
        },
        "employees": {"tax_info_token": "TEXT", "department_id": "INTEGER REFERENCES departments(department_id)"},
        "pay_periods": {"pay_period_code": "TEXT"},
        "time_entries": {
            "time_entry_code": "TEXT",
            "approval_status": "TEXT NOT NULL DEFAULT 'pending' CHECK (approval_status IN ('pending','approved','rejected'))",
            "submission_type": "TEXT NOT NULL DEFAULT 'original' CHECK (submission_type IN ('original','correction','duplicate'))",
            "supersedes_time_entry_id": "INTEGER REFERENCES time_entries(time_entry_id)",
        },
        "leave_records": {
            "supersedes_leave_id": "INTEGER REFERENCES leave_records(leave_id)",
            "created_at": "TEXT",
        },
        "allowances": {
            "allowance_code": "TEXT",
            "source_reference": "TEXT",
            "submission_type": "TEXT NOT NULL DEFAULT 'original' CHECK (submission_type IN ('original','correction','duplicate'))",
            "supersedes_allowance_id": "INTEGER REFERENCES allowances(allowance_id)",
            "eligible": "INTEGER NOT NULL DEFAULT 1 CHECK (eligible IN (0,1))",
            "created_at": "TEXT",
        },
        "deductions": {
            "deduction_code": "TEXT",
            "source_reference": "TEXT",
            "leave_id": "INTEGER REFERENCES leave_records(leave_id)",
            "submission_type": "TEXT NOT NULL DEFAULT 'original' CHECK (submission_type IN ('original','correction','duplicate'))",
            "supersedes_deduction_id": "INTEGER REFERENCES deductions(deduction_id)",
                "eligible": "INTEGER NOT NULL DEFAULT 1 CHECK (eligible IN (0,1))",
            "created_at": "TEXT",
        },
        "exceptions": {
            "exception_code": "TEXT", "finding_key": "TEXT", "anomaly_label": "TEXT",
            "employee_reference": "TEXT", "pay_period_id": "INTEGER REFERENCES pay_periods(pay_period_id)",
            "pay_period_reference": "TEXT", "entity_type": "TEXT NOT NULL DEFAULT 'unknown'",
            "validation_rule_id": "INTEGER REFERENCES validation_rules(validation_rule_id)",
            "entity_id": "TEXT NOT NULL DEFAULT 'unknown'", "expected_value": "TEXT", "actual_value": "TEXT",
            "details_json": "TEXT NOT NULL DEFAULT '{}'", "workflow_status": "TEXT NOT NULL DEFAULT 'open' CHECK (workflow_status IN ('open','under_review','resolved','rejected'))",
            "detected_at": "TEXT NOT NULL DEFAULT ''",
            "last_detected_at": "TEXT NOT NULL DEFAULT ''",
        },
        "payroll_results": {
            "payroll_run_input_id": "INTEGER REFERENCES payroll_run_inputs(payroll_run_input_id) ON UPDATE RESTRICT ON DELETE RESTRICT",
        },
    }
    for table, columns in additions.items():
        existing = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        for name, declaration in columns.items():
            if name not in existing:
                db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}')
    db.execute("INSERT OR IGNORE INTO departments(department_name) SELECT DISTINCT department FROM employees WHERE department IS NOT NULL AND trim(department)<>''")
    db.execute("UPDATE employees SET department_id=(SELECT department_id FROM departments WHERE department_name=employees.department) WHERE department_id IS NULL")
    # Migrate the former direct Employee -> PayGroup relationship into the
    # effective-dated bridge without deleting or rewriting employee records.
    db.execute(
        "INSERT OR IGNORE INTO employee_pay_group_assignments "
        "(employee_id,pay_group_id,effective_from,effective_to,status,created_by) "
        "SELECT employee_id,pay_group_id,hire_date,"
        "CASE WHEN termination_date IS NULL THEN NULL ELSE date(termination_date,'+1 day') END,"
        "CASE WHEN termination_date IS NOT NULL THEN 'ended' "
        "WHEN hire_date>date('now') THEN 'scheduled' ELSE 'active' END,'schema_migration' "
        "FROM employees e WHERE NOT EXISTS (SELECT 1 FROM employee_pay_group_assignments a "
        "WHERE a.employee_id=e.employee_id AND a.pay_group_id=e.pay_group_id "
        "AND a.effective_from=e.hire_date)"
    )
    # Link each stored result to the existing source snapshot for the same
    # payroll run and employee. Existing result rows remain untouched otherwise.
    db.execute(
        "INSERT INTO payroll_run_inputs "
        "(payroll_run_id,employee_id,pay_period_id,regular_hours,overtime_hours,paid_leave_hours,allowance_total,deduction_total) "
        "SELECT pr.payroll_run_id,pr.employee_id,r.pay_period_id,"
        "COALESCE(pi.regular_hours,pr.regular_hours),COALESCE(pi.overtime_hours,pr.overtime_hours),"
        "COALESCE(pi.paid_leave_hours,0),COALESCE(pi.allowance_total,pr.allowance_total),"
        "COALESCE(pi.deduction_total,pr.deduction_total) "
        "FROM payroll_results pr JOIN payroll_runs r USING(payroll_run_id) "
        "LEFT JOIN payroll_inputs pi ON pi.employee_id=pr.employee_id AND pi.pay_period_id=r.pay_period_id "
        "WHERE NOT EXISTS (SELECT 1 FROM payroll_run_inputs ri WHERE ri.payroll_run_id=pr.payroll_run_id "
        "AND ri.employee_id=pr.employee_id)"
    )
    db.execute(
        "UPDATE payroll_results SET payroll_run_input_id=(SELECT ri.payroll_run_input_id "
        "FROM payroll_run_inputs ri WHERE ri.payroll_run_id=payroll_results.payroll_run_id "
        "AND ri.employee_id=payroll_results.employee_id) WHERE payroll_run_input_id IS NULL"
    )
    db.execute(
        "UPDATE exceptions SET validation_rule_id=(SELECT validation_rule_id FROM validation_rules "
        "WHERE validation_rules.rule_code=exceptions.rule_code) "
        "WHERE validation_rule_id IS NULL AND EXISTS "
        "(SELECT 1 FROM validation_rules WHERE validation_rules.rule_code=exceptions.rule_code)"
    )
    # Preserve the meaning of pre-workflow exception states after adding the
    # explicit status column to an existing database.
    if "workflow_status" in {row[1] for row in db.execute('PRAGMA table_info("exceptions")')}:
        db.execute("UPDATE exceptions SET workflow_status=CASE status WHEN 'resolved' THEN 'resolved' WHEN 'waived' THEN 'rejected' WHEN 'under_review' THEN 'under_review' ELSE 'open' END WHERE workflow_status='open' AND status<>'open'")


def _ensure_relational_constraints(db):
    """Install additive guards for relations that span multiple foreign keys."""
    # Existing tables gain this FK column during _apply_additive_columns;
    # CREATE TRIGGER is intentionally delayed until that migration has run.
    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS trg_payroll_result_input_match_insert
        BEFORE INSERT ON payroll_results
        WHEN NEW.payroll_run_input_id IS NULL OR NOT EXISTS (
          SELECT 1 FROM payroll_run_inputs ri WHERE ri.payroll_run_input_id=NEW.payroll_run_input_id
            AND ri.payroll_run_id=NEW.payroll_run_id AND ri.employee_id=NEW.employee_id)
        BEGIN SELECT RAISE(ABORT,'payroll result must match its unique run input'); END;
        CREATE TRIGGER IF NOT EXISTS trg_payroll_result_input_match_update
        BEFORE UPDATE OF payroll_run_input_id,payroll_run_id,employee_id ON payroll_results
        WHEN NEW.payroll_run_input_id IS NULL OR NOT EXISTS (
          SELECT 1 FROM payroll_run_inputs ri WHERE ri.payroll_run_input_id=NEW.payroll_run_input_id
            AND ri.payroll_run_id=NEW.payroll_run_id AND ri.employee_id=NEW.employee_id)
        BEGIN SELECT RAISE(ABORT,'payroll result must match its unique run input'); END;
        CREATE TRIGGER IF NOT EXISTS trg_run_input_period_insert
        BEFORE INSERT ON payroll_run_inputs
        WHEN (SELECT pay_period_id FROM payroll_runs WHERE payroll_run_id=NEW.payroll_run_id) <> NEW.pay_period_id
        BEGIN SELECT RAISE(ABORT,'payroll run input period must match its payroll run'); END;
        CREATE TRIGGER IF NOT EXISTS trg_run_input_period_update
        BEFORE UPDATE OF payroll_run_id,pay_period_id ON payroll_run_inputs
        WHEN (SELECT pay_period_id FROM payroll_runs WHERE payroll_run_id=NEW.payroll_run_id) <> NEW.pay_period_id
        BEGIN SELECT RAISE(ABORT,'payroll run input period must match its payroll run'); END;
        CREATE TRIGGER IF NOT EXISTS trg_approval_history_link_insert
        BEFORE INSERT ON approval_history
        WHEN NOT EXISTS (
          SELECT 1 FROM payroll_inputs pi JOIN payroll_runs r ON r.pay_period_id=pi.pay_period_id
           WHERE pi.payroll_input_id=NEW.payroll_input_id AND pi.employee_id=NEW.employee_id
             AND r.payroll_run_id=NEW.payroll_run_id)
        BEGIN SELECT RAISE(ABORT,'approval history must match its payroll input and run'); END;
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update BEFORE UPDATE ON audit_events
        BEGIN SELECT RAISE(ABORT,'audit events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete BEFORE DELETE ON audit_events
        BEGIN SELECT RAISE(ABORT,'audit events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_approval_history_no_update BEFORE UPDATE ON approval_history
        BEGIN SELECT RAISE(ABORT,'approval history is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_approval_history_no_delete BEFORE DELETE ON approval_history
        BEGIN SELECT RAISE(ABORT,'approval history is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_exception_review_history_no_update BEFORE UPDATE ON exception_review_history
        BEGIN SELECT RAISE(ABORT,'exception review history is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_exception_review_history_no_delete BEFORE DELETE ON exception_review_history
        BEGIN SELECT RAISE(ABORT,'exception review history is append-only'); END;
    """)
    for table, key in PRIMARY_KEYS.items():
        trigger = f"trg_{table}_{key}_immutable"
        db.execute(
            f'CREATE TRIGGER IF NOT EXISTS "{trigger}" BEFORE UPDATE OF "{key}" ON "{table}" '
            f'WHEN NEW."{key}"<>OLD."{key}" BEGIN SELECT RAISE(ABORT,\'primary identifiers are immutable\'); END'
        )


if __name__ == "__main__":
    summary = initialize()
    print(f"Initialized and verified {DATABASE_PATH}")
    print(f"Tables: {summary['table_count']}; foreign-key relationships: {summary['foreign_key_count']}; indexes: {summary['index_count']}")
