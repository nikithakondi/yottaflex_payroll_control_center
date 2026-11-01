# Data Dictionary

Business codes are immutable, unique human-readable identifiers. Integer primary keys are used for efficient SQLite joins; foreign keys reference those primary keys.

| Table | Key fields | Purpose |
| --- | --- | --- |
| `departments` | `department_id` PK; `department_name` unique | Normalized department and cost-center master data. |
| `employees` | `employee_id` PK; `employee_number` unique; `department_id`, `pay_group_id` FKs | Employee identity, employment dates/status, salary/hourly rate, synthetic bank/tax tokens. |
| `pay_groups` | `pay_group_id` PK; `code` unique | Frequency, currency, standard hours, overtime multiplier, maximum period hours. |
| `pay_periods` | `pay_period_id` PK; `pay_period_code` unique per group; `pay_group_id` FK | Start/end/payment dates and lifecycle status. |
| `time_entries` | `time_entry_id` PK; `time_entry_code` unique; employee/period FKs; `supersedes_time_entry_id` | Daily submitted/approved hours and append-only correction/duplicate chain. |
| `leave_records` | `leave_id` PK; employee/period FKs; `supersedes_leave_id` | Paid/unpaid leave dates, hours, status, and correction chain. |
| `allowances` | `allowance_id` PK; `allowance_code` unique; employee/period FKs; `supersedes_allowance_id` | Allowance amount, taxability, eligibility, source reference, and correction chain. |
| `deductions` | `deduction_id` PK; `deduction_code` unique; employee/period FKs; optional leave FK; `supersedes_deduction_id` | Deduction amount/type, pre-tax flag, leave linkage, and correction chain. |
| `payroll_inputs` | `payroll_input_id` PK; `payroll_input_code` unique; unique employee/period | Source-derived per-employee input snapshot. |
| `validation_rules` | `validation_rule_id` PK; `rule_code` unique | Rule category, severity, active flag, and effective dates. |
| `payroll_runs` | `payroll_run_id` PK; period FK; unique period/run number | Immutable processing attempts and lifecycle status. |
| `payroll_run_inputs` | `payroll_run_input_id` PK; run/employee/period FKs | Per-run source snapshot used to calculate results. |
| `payroll_results` | `payroll_result_id` PK; unique run/employee; run/employee FKs | Regular/overtime pay, allowances, deductions, gross, net, calculation details. |
| `exceptions` | `exception_id` PK; `exception_code` and `finding_key` unique; run, employee, period, rule FKs | Finding details, severity, expected/actual values, workflow state, timestamps, resolution. |
| `approvals` | `approval_id` PK; payroll run FK | Run-level approval/export gate decision. |
| `approval_history` | `approval_id` PK; run, employee, payroll input, optional exception FKs | Append-only reviewer decisions with role, previous/new status, comments, timestamp. |
| `exception_assignments` | `assignment_id` PK; exception FK | Append-only assignment history. |
| `exception_review_history` | `review_action_id` PK; exception FK | Append-only exception review decisions. |
| `payroll_exports` | `export_id` PK; run FK | Export path, format, row count, checksum, actor, timestamp. |
| `audit_events` | `audit_event_id` PK | Append-only entity/action/actor and before/after snapshots. |

## Identifier examples

* Employee: `EMP-000001`
* Pay period: `PP-2026-01`
* Time entry: `TIME-EMP-000001-2026-01-02` (corrected/duplicate records add a revision suffix)
* Payroll input: `PIN-EMP-000001-2026-01`
* Exception: `PEX-2026-000001`

Money uses the pay group's configured currency; generated profiles currently use USD. Database timestamps are stored in SQLite's UTC `CURRENT_TIMESTAMP` format.
