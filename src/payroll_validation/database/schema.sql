PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pay_groups (
    pay_group_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    pay_frequency TEXT NOT NULL CHECK (pay_frequency IN ('monthly','semi_monthly','biweekly','weekly')),
    currency TEXT NOT NULL DEFAULT 'USD' CHECK (length(currency) = 3),
    standard_hours REAL NOT NULL DEFAULT 40 CHECK (standard_hours > 0),
    overtime_multiplier REAL NOT NULL DEFAULT 1.5 CHECK (overtime_multiplier >= 1),
    max_period_hours REAL NOT NULL DEFAULT 200 CHECK (max_period_hours > 0)
);

CREATE TABLE IF NOT EXISTS departments (
    department_id INTEGER PRIMARY KEY,
    department_name TEXT NOT NULL UNIQUE,
    cost_center TEXT UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id INTEGER PRIMARY KEY,
    employee_number TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    department TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(department_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    job_title TEXT NOT NULL,
    hire_date TEXT NOT NULL,
    termination_date TEXT,
    pay_group_id INTEGER NOT NULL REFERENCES pay_groups(pay_group_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    employment_status TEXT NOT NULL CHECK (employment_status IN ('active','terminated','on_leave')),
    standard_hours REAL NOT NULL DEFAULT 40 CHECK (standard_hours >= 0),
    annual_salary REAL NOT NULL CHECK (annual_salary >= 0),
    hourly_rate REAL NOT NULL CHECK (hourly_rate >= 0),
    bank_account_token TEXT,
    tax_info_token TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (termination_date IS NULL OR termination_date >= hire_date)
);

-- Effective-dated employee/pay-group membership. This associative entity makes
-- the historical Employee <-> PayGroup relationship explicit; pay_group_id on
-- employees remains the current compatibility key used by existing services.
-- effective_to is exclusive so adjacent assignments can meet without overlap.
CREATE TABLE IF NOT EXISTS employee_pay_group_assignments (
    assignment_id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_group_id INTEGER NOT NULL REFERENCES pay_groups(pay_group_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    effective_from TEXT NOT NULL CHECK (length(effective_from)=10 AND date(effective_from)=effective_from),
    effective_to TEXT CHECK (effective_to IS NULL OR (length(effective_to)=10 AND date(effective_to)=effective_to)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('scheduled','active','ended','cancelled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL DEFAULT 'system',
    notes TEXT,
    UNIQUE (employee_id, effective_from),
    CHECK (effective_to IS NULL OR effective_to > effective_from
           OR (status='cancelled' AND effective_to=effective_from)),
    CHECK (status <> 'ended' OR effective_to IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS pay_periods (
    pay_period_id INTEGER PRIMARY KEY,
    pay_group_id INTEGER NOT NULL REFERENCES pay_groups(pay_group_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    payment_date TEXT NOT NULL,
    pay_period_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','processing','validated','approved','exported','closed')),
    UNIQUE (pay_group_id, period_start, period_end),
    UNIQUE (pay_group_id, pay_period_code),
    CHECK (period_start <= period_end),
    CHECK (payment_date >= period_end)
);

CREATE TABLE IF NOT EXISTS validation_rules (
    validation_rule_id INTEGER PRIMARY KEY,
    rule_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    effective_from TEXT NOT NULL DEFAULT '2026-01-01',
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_from <= effective_to)
);

INSERT INTO validation_rules(rule_code,name,description,severity) VALUES
 ('HOURS_PERIOD_MAX','Period hours maximum','Effective approved hours must not exceed the configured pay-period maximum.','critical'),
 ('DUPLICATE_ALLOWANCE','Duplicate allowance','A source allowance submission must not be counted more than once.','critical'),
 ('TIME_UNAPPROVED','Unapproved time','Pending or rejected time cannot be included in payroll.','critical'),
 ('DUP_UNPAID_LEAVE_DEDUCTION','Duplicate unpaid leave deduction','An approved unpaid leave must have exactly one linked deduction.','critical'),
 ('PAYROLL_RECONCILIATION','Payroll reconciliation','Gross and net totals must reconcile to calculated components.','critical'),
 ('BANK_DETAILS_MISSING','Missing bank details','Active payroll employees require bank account details.','critical'),
 ('TAX_INFORMATION_MISSING','Missing tax information','Active payroll employees require tax information.','critical'),
 ('DUPLICATE_TIME_ENTRY','Duplicate time entry','Only one effective approved entry is permitted per employee and work date.','critical'),
 ('INCORRECT_PAYROLL_CALCULATION','Incorrect payroll calculation','Payroll inputs and results must match source-derived values.','critical'),
 ('INVALID_REFERENCE','Invalid reference','Imported payroll source references must resolve to valid employee and pay-period records.','critical'),
 ('DATE_OUTSIDE_PERIOD','Date outside pay period','Time and leave dates must fall inside their linked pay period.','critical')
ON CONFLICT(rule_code) DO UPDATE SET name=excluded.name,description=excluded.description,severity=excluded.severity;

CREATE TABLE IF NOT EXISTS time_entries (
    time_entry_id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_period_id INTEGER NOT NULL REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    work_date TEXT NOT NULL,
    time_entry_code TEXT NOT NULL UNIQUE,
    regular_hours REAL NOT NULL DEFAULT 0 CHECK (regular_hours >= 0),
    overtime_hours REAL NOT NULL DEFAULT 0 CHECK (overtime_hours >= 0),
    source TEXT NOT NULL DEFAULT 'synthetic',
    status TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('draft','submitted','approved','rejected')),
    approval_status TEXT NOT NULL DEFAULT 'pending' CHECK (approval_status IN ('pending','approved','rejected')),
    submission_type TEXT NOT NULL DEFAULT 'original' CHECK (submission_type IN ('original','correction','duplicate')),
    supersedes_time_entry_id INTEGER REFERENCES time_entries(time_entry_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS leave_records (
    leave_id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_period_id INTEGER NOT NULL REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    leave_type TEXT NOT NULL CHECK (leave_type IN ('paid','unpaid')),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    hours REAL NOT NULL CHECK (hours >= 0),
    status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','cancelled')),
    supersedes_leave_id INTEGER REFERENCES leave_records(leave_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (start_date <= end_date)
);

CREATE TABLE IF NOT EXISTS allowances (
    allowance_id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_period_id INTEGER NOT NULL REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    allowance_type TEXT NOT NULL CHECK (trim(allowance_type) <> ''),
    allowance_code TEXT NOT NULL UNIQUE,
    source_reference TEXT NOT NULL,
    submission_type TEXT NOT NULL DEFAULT 'original' CHECK (submission_type IN ('original','correction','duplicate')),
    amount REAL NOT NULL CHECK (amount >= 0),
    taxable INTEGER NOT NULL DEFAULT 1 CHECK (taxable IN (0,1)),
    eligible INTEGER NOT NULL DEFAULT 1 CHECK (eligible IN (0,1)),
    description TEXT,
    supersedes_allowance_id INTEGER REFERENCES allowances(allowance_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deductions (
    deduction_id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_period_id INTEGER NOT NULL REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    deduction_type TEXT NOT NULL CHECK (trim(deduction_type) <> ''),
    deduction_code TEXT NOT NULL UNIQUE,
    source_reference TEXT NOT NULL,
    leave_id INTEGER REFERENCES leave_records(leave_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    submission_type TEXT NOT NULL DEFAULT 'original' CHECK (submission_type IN ('original','correction','duplicate')),
    amount REAL NOT NULL CHECK (amount >= 0),
    pre_tax INTEGER NOT NULL DEFAULT 0 CHECK (pre_tax IN (0,1)),
    eligible INTEGER NOT NULL DEFAULT 1 CHECK (eligible IN (0,1)),
    description TEXT,
    supersedes_deduction_id INTEGER REFERENCES deductions(deduction_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payroll_runs (
    payroll_run_id INTEGER PRIMARY KEY,
    pay_period_id INTEGER NOT NULL REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    run_number INTEGER NOT NULL CHECK (run_number > 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','processed','validated','approved','exported','failed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL DEFAULT 'system',
    UNIQUE (pay_period_id, run_number)
);

CREATE TABLE IF NOT EXISTS payroll_results (
    payroll_result_id INTEGER PRIMARY KEY,
    payroll_run_input_id INTEGER NOT NULL UNIQUE REFERENCES payroll_run_inputs(payroll_run_input_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    payroll_run_id INTEGER NOT NULL REFERENCES payroll_runs(payroll_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    regular_hours REAL NOT NULL CHECK (regular_hours >= 0),
    overtime_hours REAL NOT NULL CHECK (overtime_hours >= 0),
    regular_pay REAL NOT NULL CHECK (regular_pay >= 0),
    overtime_pay REAL NOT NULL CHECK (overtime_pay >= 0),
    allowance_total REAL NOT NULL CHECK (allowance_total >= 0),
    deduction_total REAL NOT NULL CHECK (deduction_total >= 0),
    gross_pay REAL NOT NULL CHECK (gross_pay >= 0),
    net_pay REAL NOT NULL CHECK (net_pay >= 0),
    calculation_details TEXT NOT NULL DEFAULT '{}',
    UNIQUE (payroll_run_id, employee_id)
);

CREATE TABLE IF NOT EXISTS payroll_inputs (
    payroll_input_id INTEGER PRIMARY KEY,
    payroll_input_code TEXT NOT NULL UNIQUE,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_period_id INTEGER NOT NULL REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    regular_hours REAL NOT NULL CHECK (regular_hours >= 0),
    overtime_hours REAL NOT NULL CHECK (overtime_hours >= 0),
    paid_leave_hours REAL NOT NULL CHECK (paid_leave_hours >= 0),
    allowance_total REAL NOT NULL CHECK (allowance_total >= 0),
    deduction_total REAL NOT NULL CHECK (deduction_total >= 0),
    UNIQUE (employee_id, pay_period_id)
);

CREATE TABLE IF NOT EXISTS payroll_run_inputs (
    payroll_run_input_id INTEGER PRIMARY KEY,
    payroll_run_id INTEGER NOT NULL REFERENCES payroll_runs(payroll_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_period_id INTEGER NOT NULL REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    regular_hours REAL NOT NULL CHECK (regular_hours >= 0),
    overtime_hours REAL NOT NULL CHECK (overtime_hours >= 0),
    paid_leave_hours REAL NOT NULL CHECK (paid_leave_hours >= 0),
    allowance_total REAL NOT NULL CHECK (allowance_total >= 0),
    deduction_total REAL NOT NULL CHECK (deduction_total >= 0),
    UNIQUE (payroll_run_id, employee_id)
);

CREATE TABLE IF NOT EXISTS exceptions (
    exception_id INTEGER PRIMARY KEY,
    exception_code TEXT NOT NULL UNIQUE,
    finding_key TEXT NOT NULL UNIQUE,
    anomaly_label TEXT NOT NULL,
    payroll_run_id INTEGER NOT NULL REFERENCES payroll_runs(payroll_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    employee_id INTEGER REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    employee_reference TEXT,
    pay_period_id INTEGER REFERENCES pay_periods(pay_period_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pay_period_reference TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    rule_code TEXT NOT NULL,
    validation_rule_id INTEGER REFERENCES validation_rules(validation_rule_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    message TEXT NOT NULL,
    expected_value TEXT,
    actual_value TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','under_review','resolved','waived')),
    workflow_status TEXT NOT NULL DEFAULT 'open' CHECK (workflow_status IN ('open','under_review','resolved','rejected')),
    resolution TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    CHECK ((status IN ('resolved','waived') AND resolved_at IS NOT NULL) OR status IN ('open','under_review'))
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id INTEGER PRIMARY KEY,
    payroll_run_id INTEGER NOT NULL REFERENCES payroll_runs(payroll_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    approver TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
    comments TEXT,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approval_history (
    approval_id INTEGER PRIMARY KEY,
    payroll_run_id INTEGER NOT NULL REFERENCES payroll_runs(payroll_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    payroll_input_id INTEGER NOT NULL REFERENCES payroll_inputs(payroll_input_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reviewer_id TEXT NOT NULL,
    reviewer_role TEXT NOT NULL CHECK (reviewer_role IN ('Employee','Manager','HR Partner','IT/Operations Partner','System Administrator')),
    previous_status TEXT NOT NULL CHECK (previous_status IN ('pending','approved','rejected','correction_required')),
    new_status TEXT NOT NULL CHECK (new_status IN ('pending','approved','rejected','correction_required')),
    action_type TEXT NOT NULL,
    action_timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    comments TEXT,
    exception_id INTEGER REFERENCES exceptions(exception_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS exception_assignments (
    assignment_id INTEGER PRIMARY KEY,
    exception_id INTEGER NOT NULL REFERENCES exceptions(exception_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    assignee_id TEXT NOT NULL,
    assignee_role TEXT NOT NULL CHECK (assignee_role IN ('Employee','Manager','HR Partner','IT/Operations Partner','System Administrator')),
    assigned_by TEXT NOT NULL,
    assigned_by_role TEXT NOT NULL CHECK (assigned_by_role IN ('Employee','Manager','HR Partner','IT/Operations Partner','System Administrator')),
    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    comments TEXT
);

CREATE TABLE IF NOT EXISTS exception_review_history (
    review_action_id INTEGER PRIMARY KEY,
    exception_id INTEGER NOT NULL REFERENCES exceptions(exception_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reviewer_id TEXT NOT NULL,
    reviewer_role TEXT NOT NULL CHECK (reviewer_role IN ('Employee','Manager','HR Partner','IT/Operations Partner','System Administrator')),
    previous_status TEXT NOT NULL CHECK (previous_status IN ('open','under_review','resolved','rejected')),
    new_status TEXT NOT NULL CHECK (new_status IN ('open','under_review','resolved','rejected')),
    action_timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    comments TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payroll_exports (
    export_id INTEGER PRIMARY KEY,
    payroll_run_id INTEGER NOT NULL REFERENCES payroll_runs(payroll_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    file_path TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('csv','xlsx','json')),
    exported_by TEXT NOT NULL,
    exported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    checksum TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    before_json TEXT,
    after_json TEXT,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Decision and audit records are append-only so prior approvals/reviews and
-- before/after snapshots cannot be silently rewritten or removed.
CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_approval_history_no_update BEFORE UPDATE ON approval_history
BEGIN SELECT RAISE(ABORT, 'approval history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_approval_history_no_delete BEFORE DELETE ON approval_history
BEGIN SELECT RAISE(ABORT, 'approval history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_exception_review_history_no_update BEFORE UPDATE ON exception_review_history
BEGIN SELECT RAISE(ABORT, 'exception review history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_exception_review_history_no_delete BEFORE DELETE ON exception_review_history
BEGIN SELECT RAISE(ABORT, 'exception review history is append-only'); END;

-- Add assignment history automatically for every employee created through
-- SQL or application code; initialization backfills the same relation for
-- existing rows.
CREATE TRIGGER IF NOT EXISTS trg_employee_assignment_after_insert
AFTER INSERT ON employees
BEGIN
  INSERT INTO employee_pay_group_assignments(employee_id,pay_group_id,effective_from,effective_to,status,created_by)
  VALUES (NEW.employee_id,NEW.pay_group_id,NEW.hire_date,
          CASE WHEN NEW.termination_date IS NULL THEN NULL ELSE date(NEW.termination_date,'+1 day') END,
          CASE WHEN NEW.employment_status='terminated' THEN 'ended'
               WHEN NEW.hire_date > date('now') THEN 'scheduled' ELSE 'active' END,
          'employee_insert');
END;

CREATE TRIGGER IF NOT EXISTS trg_employee_department_insert
BEFORE INSERT ON employees
WHEN NEW.department_id IS NULL OR
     (SELECT department_name FROM departments WHERE department_id=NEW.department_id) IS NULL OR
     (SELECT department_name FROM departments WHERE department_id=NEW.department_id) <> NEW.department
BEGIN SELECT RAISE(ABORT, 'employee department must match a department record'); END;
CREATE TRIGGER IF NOT EXISTS trg_employee_department_update
BEFORE UPDATE OF department,department_id ON employees
WHEN NEW.department_id IS NULL OR
     (SELECT department_name FROM departments WHERE department_id=NEW.department_id) IS NULL OR
     (SELECT department_name FROM departments WHERE department_id=NEW.department_id) <> NEW.department
BEGIN SELECT RAISE(ABORT, 'employee department must match a department record'); END;

CREATE TRIGGER IF NOT EXISTS trg_exception_rule_link_insert
BEFORE INSERT ON exceptions
WHEN NEW.validation_rule_id IS NULL OR NOT EXISTS (
  SELECT 1 FROM validation_rules vr WHERE vr.validation_rule_id=NEW.validation_rule_id AND vr.rule_code=NEW.rule_code
)
BEGIN SELECT RAISE(ABORT, 'exception must reference its matching validation rule'); END;
CREATE TRIGGER IF NOT EXISTS trg_exception_rule_link_update
BEFORE UPDATE OF validation_rule_id,rule_code ON exceptions
WHEN NEW.validation_rule_id IS NULL OR NOT EXISTS (
  SELECT 1 FROM validation_rules vr WHERE vr.validation_rule_id=NEW.validation_rule_id AND vr.rule_code=NEW.rule_code
)
BEGIN SELECT RAISE(ABORT, 'exception must reference its matching validation rule'); END;

CREATE TRIGGER IF NOT EXISTS trg_employee_assignment_after_group_update
AFTER UPDATE OF pay_group_id ON employees
WHEN NEW.pay_group_id <> OLD.pay_group_id
BEGIN
  UPDATE employee_pay_group_assignments
     SET effective_to=CASE WHEN effective_from >= date('now') THEN effective_from ELSE date('now') END,
         status=CASE WHEN effective_from >= date('now') THEN 'cancelled' ELSE 'ended' END
   WHERE employee_id=NEW.employee_id AND status IN ('active','scheduled') AND effective_to IS NULL;
  INSERT INTO employee_pay_group_assignments(employee_id,pay_group_id,effective_from,status,created_by)
  VALUES (NEW.employee_id,NEW.pay_group_id,
          CASE WHEN NEW.hire_date > date('now') THEN NEW.hire_date ELSE date('now') END,
          CASE WHEN NEW.hire_date > date('now') THEN 'scheduled' ELSE 'active' END,
          'employee_group_update');
END;

CREATE TRIGGER IF NOT EXISTS trg_employee_group_assignment_no_overlap_insert
BEFORE INSERT ON employee_pay_group_assignments
WHEN NEW.status <> 'cancelled' AND EXISTS (
  SELECT 1 FROM employee_pay_group_assignments a
   WHERE a.employee_id=NEW.employee_id AND a.status <> 'cancelled'
     AND (a.effective_to IS NULL OR NEW.effective_from < a.effective_to)
     AND (NEW.effective_to IS NULL OR a.effective_from < NEW.effective_to)
)
BEGIN SELECT RAISE(ABORT, 'employee pay-group assignments cannot overlap'); END;

CREATE TRIGGER IF NOT EXISTS trg_employee_group_assignment_no_overlap_update
BEFORE UPDATE OF employee_id,pay_group_id,effective_from,effective_to,status ON employee_pay_group_assignments
WHEN NEW.status <> 'cancelled' AND EXISTS (
  SELECT 1 FROM employee_pay_group_assignments a
   WHERE a.employee_id=NEW.employee_id AND a.assignment_id<>NEW.assignment_id AND a.status <> 'cancelled'
     AND (a.effective_to IS NULL OR NEW.effective_from < a.effective_to)
     AND (NEW.effective_to IS NULL OR a.effective_from < NEW.effective_to)
)
BEGIN SELECT RAISE(ABORT, 'employee pay-group assignments cannot overlap'); END;

-- A run input is a snapshot for exactly the period processed by its run.
CREATE TRIGGER IF NOT EXISTS trg_run_input_period_insert
BEFORE INSERT ON payroll_run_inputs
WHEN (SELECT pay_period_id FROM payroll_runs WHERE payroll_run_id=NEW.payroll_run_id) <> NEW.pay_period_id
BEGIN SELECT RAISE(ABORT, 'payroll run input period must match its payroll run'); END;
CREATE TRIGGER IF NOT EXISTS trg_run_input_period_update
BEFORE UPDATE OF payroll_run_id,pay_period_id ON payroll_run_inputs
WHEN (SELECT pay_period_id FROM payroll_runs WHERE payroll_run_id=NEW.payroll_run_id) <> NEW.pay_period_id
BEGIN SELECT RAISE(ABORT, 'payroll run input period must match its payroll run'); END;

-- Enforce the one-to-one PayrollRunInput <-> PayrollResult relationship and
-- the employee/run composite identity in addition to the direct foreign key.
-- Approval history must refer to an input for the same employee and run period.
CREATE TRIGGER IF NOT EXISTS trg_approval_history_link_insert
BEFORE INSERT ON approval_history
WHEN NOT EXISTS (
  SELECT 1 FROM payroll_inputs pi JOIN payroll_runs r ON r.pay_period_id=pi.pay_period_id
   WHERE pi.payroll_input_id=NEW.payroll_input_id AND pi.employee_id=NEW.employee_id
     AND r.payroll_run_id=NEW.payroll_run_id
)
BEGIN SELECT RAISE(ABORT, 'approval history must match its payroll input and run'); END;

-- Export-once is protected both in the service and at the database boundary.
CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_exports_one_per_run ON payroll_exports(payroll_run_id);
CREATE INDEX IF NOT EXISTS idx_employee_group_assignment_effective ON employee_pay_group_assignments(employee_id,effective_from,effective_to);
CREATE INDEX IF NOT EXISTS idx_group_assignment_effective ON employee_pay_group_assignments(pay_group_id,effective_from,effective_to);

-- An employee can only have source records and results in periods belonging
-- to that employee's assigned pay group. These checks supplement the FKs.
CREATE TRIGGER IF NOT EXISTS trg_time_entry_pay_group_insert
BEFORE INSERT ON time_entries
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'time entry employee and pay period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_time_entry_pay_group_update
BEFORE UPDATE OF employee_id, pay_period_id ON time_entries
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'time entry employee and pay period groups differ'); END;

CREATE TRIGGER IF NOT EXISTS trg_leave_pay_group_insert
BEFORE INSERT ON leave_records
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'leave employee and pay period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_leave_pay_group_update
BEFORE UPDATE OF employee_id, pay_period_id ON leave_records
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'leave employee and pay period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_time_entry_date_insert
BEFORE INSERT ON time_entries
WHEN (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id) IS NOT NULL
 AND (NEW.work_date < (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id)
 OR NEW.work_date > (SELECT period_end FROM pay_periods WHERE pay_period_id=NEW.pay_period_id))
BEGIN SELECT RAISE(ABORT, 'time entry date is outside its pay period'); END;
CREATE TRIGGER IF NOT EXISTS trg_time_entry_date_update
BEFORE UPDATE OF work_date,pay_period_id ON time_entries
WHEN (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id) IS NOT NULL
 AND (NEW.work_date < (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id)
 OR NEW.work_date > (SELECT period_end FROM pay_periods WHERE pay_period_id=NEW.pay_period_id))
BEGIN SELECT RAISE(ABORT, 'time entry date is outside its pay period'); END;
CREATE TRIGGER IF NOT EXISTS trg_leave_date_insert
BEFORE INSERT ON leave_records
WHEN (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id) IS NOT NULL
 AND (NEW.start_date < (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id)
 OR NEW.end_date > (SELECT period_end FROM pay_periods WHERE pay_period_id=NEW.pay_period_id))
BEGIN SELECT RAISE(ABORT, 'leave dates are outside their pay period'); END;
CREATE TRIGGER IF NOT EXISTS trg_leave_date_update
BEFORE UPDATE OF start_date,end_date,pay_period_id ON leave_records
WHEN (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id) IS NOT NULL
 AND (NEW.start_date < (SELECT period_start FROM pay_periods WHERE pay_period_id=NEW.pay_period_id)
 OR NEW.end_date > (SELECT period_end FROM pay_periods WHERE pay_period_id=NEW.pay_period_id))
BEGIN SELECT RAISE(ABORT, 'leave dates are outside their pay period'); END;

-- Human-readable business identifiers are stable once issued.
CREATE TRIGGER IF NOT EXISTS trg_employee_number_immutable BEFORE UPDATE OF employee_number ON employees
WHEN NEW.employee_number != OLD.employee_number BEGIN SELECT RAISE(ABORT, 'employee identifiers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_pay_group_code_immutable BEFORE UPDATE OF code ON pay_groups
WHEN NEW.code != OLD.code BEGIN SELECT RAISE(ABORT, 'pay group identifiers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_pay_period_code_immutable BEFORE UPDATE OF pay_period_code ON pay_periods
WHEN NEW.pay_period_code != OLD.pay_period_code BEGIN SELECT RAISE(ABORT, 'pay period identifiers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_time_entry_code_immutable BEFORE UPDATE OF time_entry_code ON time_entries
WHEN NEW.time_entry_code != OLD.time_entry_code BEGIN SELECT RAISE(ABORT, 'time entry identifiers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_payroll_input_code_immutable BEFORE UPDATE OF payroll_input_code ON payroll_inputs
WHEN NEW.payroll_input_code != OLD.payroll_input_code BEGIN SELECT RAISE(ABORT, 'payroll input identifiers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_exception_code_immutable BEFORE UPDATE OF exception_code ON exceptions
WHEN NEW.exception_code != OLD.exception_code BEGIN SELECT RAISE(ABORT, 'exception identifiers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_allowance_code_immutable BEFORE UPDATE OF allowance_code ON allowances
WHEN NEW.allowance_code != OLD.allowance_code BEGIN SELECT RAISE(ABORT, 'allowance identifiers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_deduction_code_immutable BEFORE UPDATE OF deduction_code ON deductions
WHEN NEW.deduction_code != OLD.deduction_code BEGIN SELECT RAISE(ABORT, 'deduction identifiers are immutable'); END;

CREATE TRIGGER IF NOT EXISTS trg_allowance_pay_group_insert
BEFORE INSERT ON allowances
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'allowance employee and pay period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_allowance_pay_group_update
BEFORE UPDATE OF employee_id, pay_period_id ON allowances
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'allowance employee and pay period groups differ'); END;

CREATE TRIGGER IF NOT EXISTS trg_deduction_pay_group_insert
BEFORE INSERT ON deductions
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'deduction employee and pay period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_deduction_pay_group_update
BEFORE UPDATE OF employee_id, pay_period_id ON deductions
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'deduction employee and pay period groups differ'); END;

CREATE TRIGGER IF NOT EXISTS trg_payroll_result_pay_group_insert
BEFORE INSERT ON payroll_results
WHEN (SELECT e.pay_group_id FROM employees e WHERE e.employee_id = NEW.employee_id)
     != (SELECT p.pay_group_id FROM payroll_runs r JOIN pay_periods p ON p.pay_period_id = r.pay_period_id WHERE r.payroll_run_id = NEW.payroll_run_id)
BEGIN SELECT RAISE(ABORT, 'payroll result employee and run period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_payroll_result_pay_group_update
BEFORE UPDATE OF employee_id, payroll_run_id ON payroll_results
WHEN (SELECT e.pay_group_id FROM employees e WHERE e.employee_id = NEW.employee_id)
     != (SELECT p.pay_group_id FROM payroll_runs r JOIN pay_periods p ON p.pay_period_id = r.pay_period_id WHERE r.payroll_run_id = NEW.payroll_run_id)
BEGIN SELECT RAISE(ABORT, 'payroll result employee and run period groups differ'); END;

CREATE TRIGGER IF NOT EXISTS trg_payroll_input_pay_group_insert
BEFORE INSERT ON payroll_inputs
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'payroll input employee and pay period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_payroll_input_pay_group_update
BEFORE UPDATE OF employee_id, pay_period_id ON payroll_inputs
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'payroll input employee and pay period groups differ'); END;
CREATE TRIGGER IF NOT EXISTS trg_payroll_run_input_pay_group_insert
BEFORE INSERT ON payroll_run_inputs
WHEN (SELECT pay_group_id FROM employees WHERE employee_id = NEW.employee_id)
     != (SELECT pay_group_id FROM pay_periods WHERE pay_period_id = NEW.pay_period_id)
BEGIN SELECT RAISE(ABORT, 'payroll run input employee and pay period groups differ'); END;

CREATE TRIGGER IF NOT EXISTS trg_employee_group_update_guard
BEFORE UPDATE OF pay_group_id ON employees
WHEN EXISTS (SELECT 1 FROM pay_periods p WHERE p.pay_group_id != NEW.pay_group_id AND (
    EXISTS (SELECT 1 FROM time_entries t WHERE t.employee_id = OLD.employee_id AND t.pay_period_id = p.pay_period_id) OR
    EXISTS (SELECT 1 FROM leave_records l WHERE l.employee_id = OLD.employee_id AND l.pay_period_id = p.pay_period_id) OR
    EXISTS (SELECT 1 FROM allowances a WHERE a.employee_id = OLD.employee_id AND a.pay_period_id = p.pay_period_id) OR
    EXISTS (SELECT 1 FROM deductions d WHERE d.employee_id = OLD.employee_id AND d.pay_period_id = p.pay_period_id) OR
    EXISTS (SELECT 1 FROM payroll_results pr JOIN payroll_runs r ON r.payroll_run_id = pr.payroll_run_id WHERE pr.employee_id = OLD.employee_id AND r.pay_period_id = p.pay_period_id)
))
BEGIN SELECT RAISE(ABORT, 'employee group change would invalidate payroll relationships'); END;
CREATE TRIGGER IF NOT EXISTS trg_period_group_update_guard
BEFORE UPDATE OF pay_group_id ON pay_periods
WHEN EXISTS (SELECT 1 FROM employees e WHERE e.pay_group_id != NEW.pay_group_id AND (
    EXISTS (SELECT 1 FROM time_entries t WHERE t.employee_id = e.employee_id AND t.pay_period_id = OLD.pay_period_id) OR
    EXISTS (SELECT 1 FROM leave_records l WHERE l.employee_id = e.employee_id AND l.pay_period_id = OLD.pay_period_id) OR
    EXISTS (SELECT 1 FROM allowances a WHERE a.employee_id = e.employee_id AND a.pay_period_id = OLD.pay_period_id) OR
    EXISTS (SELECT 1 FROM deductions d WHERE d.employee_id = e.employee_id AND d.pay_period_id = OLD.pay_period_id) OR
    EXISTS (SELECT 1 FROM payroll_runs r JOIN payroll_results pr ON pr.payroll_run_id = r.payroll_run_id WHERE pr.employee_id = e.employee_id AND r.pay_period_id = OLD.pay_period_id)
))
BEGIN SELECT RAISE(ABORT, 'period group change would invalidate payroll relationships'); END;

CREATE INDEX IF NOT EXISTS idx_employees_pay_group ON employees(pay_group_id);
CREATE INDEX IF NOT EXISTS idx_validation_rules_active ON validation_rules(is_active,rule_code);
CREATE INDEX IF NOT EXISTS idx_periods_group_dates ON pay_periods(pay_group_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_time_employee_period ON time_entries(employee_id, pay_period_id);
CREATE INDEX IF NOT EXISTS idx_time_period_date ON time_entries(pay_period_id, work_date);
CREATE INDEX IF NOT EXISTS idx_leave_employee_period ON leave_records(employee_id, pay_period_id);
CREATE INDEX IF NOT EXISTS idx_allowance_employee_period ON allowances(employee_id, pay_period_id);
CREATE INDEX IF NOT EXISTS idx_deduction_employee_period ON deductions(employee_id, pay_period_id);
CREATE INDEX IF NOT EXISTS idx_runs_period_status ON payroll_runs(pay_period_id, status);
CREATE INDEX IF NOT EXISTS idx_results_run ON payroll_results(payroll_run_id);
CREATE INDEX IF NOT EXISTS idx_payroll_inputs_period_employee ON payroll_inputs(pay_period_id, employee_id);
CREATE INDEX IF NOT EXISTS idx_run_inputs_run_employee ON payroll_run_inputs(payroll_run_id, employee_id);
CREATE INDEX IF NOT EXISTS idx_results_employee ON payroll_results(employee_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_run_status ON exceptions(payroll_run_id, status);
CREATE INDEX IF NOT EXISTS idx_exceptions_employee ON exceptions(employee_id);
CREATE INDEX IF NOT EXISTS idx_approval_history_run_input ON approval_history(payroll_run_id,payroll_input_id,approval_id);
CREATE INDEX IF NOT EXISTS idx_exception_assignments_exception ON exception_assignments(exception_id,assignment_id);
CREATE INDEX IF NOT EXISTS idx_exception_review_history_exception ON exception_review_history(exception_id,review_action_id);
CREATE INDEX IF NOT EXISTS idx_approvals_run_time ON approvals(payroll_run_id, decided_at);
CREATE INDEX IF NOT EXISTS idx_exports_run_time ON payroll_exports(payroll_run_id, exported_at);
CREATE INDEX IF NOT EXISTS idx_audit_entity_time ON audit_events(entity_type, entity_id, occurred_at);
