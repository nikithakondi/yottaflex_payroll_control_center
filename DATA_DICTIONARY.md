# Data Dictionary

Generated from the current SQLite schema on 2026-10-31. The authoritative DDL is [`schema.sql`](../src/payroll_validation/database/schema.sql). SQLite declarations are shown as stored; `REAL` monetary values are rounded to two decimal places by payroll services.

## Relationship model

- One PayGroup has many PayPeriods and current Employee references. Employee-to-PayGroup history is many-to-many through `employee_pay_group_assignments`, with non-overlapping effective intervals.
- One Employee has many TimeEntries, LeaveRecords, Allowances, Deductions, PayrollInputs and PayrollResults; each source row belongs to one PayPeriod.
- One PayPeriod has many PayrollRuns and PayrollInputs. Each PayrollRun has many PayrollRunInputs, PayrollResults, Exceptions and exports.
- `payroll_run_inputs` links a PayrollRun and Employee for one period. `payroll_results.payroll_run_input_id` is a unique FK, enforcing one-to-one run-input/result pairing.
- One ValidationRule classifies many Exceptions. Approval, assignment and exception-review history are one-to-many event tables.
- `audit_events.entity_type/entity_id` is intentionally polymorphic across entity tables; actor IDs are external/demo identities, so these two text fields do not use a single entity FK.

For each field: **Required** means `NOT NULL` or primary key in the canonical schema; **Allowed values** lists enumerations/check values when restricted; **Unique** identifies column or composite uniqueness; **Validation** summarizes checks, foreign keys and immutable identifier rules. A dash means no additional field-level enumeration/unit/unique rule.

## `allowances`

Allowance amounts, eligibility, source references and correction lineage.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `allowance_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `employee_id` | INTEGER | Yes | — | — | — | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `pay_period_id` | INTEGER | Yes | — | — | — | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `allowance_type` | TEXT | Yes | — | — | — | NOT NULL |
| `allowance_code` | TEXT | Yes | — | — | UNIQUE(allowance_code) | NOT NULL |
| `source_reference` | TEXT | Yes | — | — | — | NOT NULL |
| `submission_type` | TEXT | Yes | original \| correction \| duplicate | — | — | NOT NULL; Default 'original'; CHECK/trigger restricts the allowed values listed |
| `amount` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `taxable` | INTEGER | Yes | 0 \| 1 (false \| true) | — | — | NOT NULL; Default 1; CHECK/trigger restricts the allowed values listed |
| `eligible` | INTEGER | Yes | 0 \| 1 (false \| true) | — | — | NOT NULL; Default 1; CHECK/trigger restricts the allowed values listed |
| `description` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `supersedes_allowance_id` | INTEGER | No | — | — | — | FK → allowances.allowance_id (ON UPDATE/DELETE RESTRICT) |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `approval_history`

Append-only per-input reviewer decision history.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `approval_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `payroll_run_id` | INTEGER | Yes | — | — | — | FK → payroll_runs.payroll_run_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `employee_id` | INTEGER | Yes | — | — | — | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `payroll_input_id` | INTEGER | Yes | — | — | — | FK → payroll_inputs.payroll_input_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `reviewer_id` | TEXT | Yes | — | — | — | NOT NULL |
| `reviewer_role` | TEXT | Yes | Employee \| Manager \| HR Partner \| IT/Operations Partner \| System Administrator | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `previous_status` | TEXT | Yes | pending \| approved \| rejected \| correction_required | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `new_status` | TEXT | Yes | pending \| approved \| rejected \| correction_required | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `action_type` | TEXT | Yes | — | — | — | NOT NULL |
| `action_timestamp` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `comments` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `exception_id` | INTEGER | No | — | — | — | FK → exceptions.exception_id (ON UPDATE/DELETE RESTRICT) |

## `approvals`

Run-level approval decisions.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `approval_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `payroll_run_id` | INTEGER | Yes | — | — | — | FK → payroll_runs.payroll_run_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `approver` | TEXT | Yes | — | — | — | NOT NULL |
| `decision` | TEXT | Yes | approved \| rejected | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `comments` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `decided_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `audit_events`

Append-only event snapshots for entities and workflow actions.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `audit_event_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `entity_type` | TEXT | Yes | — | — | — | NOT NULL |
| `entity_id` | TEXT | Yes | — | — | — | NOT NULL |
| `action` | TEXT | Yes | — | — | — | NOT NULL |
| `actor` | TEXT | Yes | — | — | — | NOT NULL; Default 'system' |
| `before_json` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `after_json` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `occurred_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `deductions`

Deduction amounts, leave linkage, source references and correction lineage.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `deduction_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `employee_id` | INTEGER | Yes | — | — | — | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `pay_period_id` | INTEGER | Yes | — | — | — | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `deduction_type` | TEXT | Yes | — | — | — | NOT NULL |
| `deduction_code` | TEXT | Yes | — | — | UNIQUE(deduction_code) | NOT NULL |
| `source_reference` | TEXT | Yes | — | — | — | NOT NULL |
| `leave_id` | INTEGER | No | — | — | — | FK → leave_records.leave_id (ON UPDATE/DELETE RESTRICT) |
| `submission_type` | TEXT | Yes | original \| correction \| duplicate | — | — | NOT NULL; Default 'original'; CHECK/trigger restricts the allowed values listed |
| `amount` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `pre_tax` | INTEGER | Yes | 0 \| 1 (false \| true) | — | — | NOT NULL; Default 0; CHECK/trigger restricts the allowed values listed |
| `eligible` | INTEGER | Yes | 0 \| 1 (false \| true) | — | — | NOT NULL; Default 1; CHECK restricts values; only eligible deductions enter calculated payroll totals |
| `description` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `supersedes_deduction_id` | INTEGER | No | — | — | — | FK → deductions.deduction_id (ON UPDATE/DELETE RESTRICT) |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `departments`

Normalized employee departments and cost centers.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `department_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `department_name` | TEXT | Yes | — | — | UNIQUE(department_name) | NOT NULL |
| `cost_center` | TEXT | No | — | — | UNIQUE(cost_center) | No additional field-level check; see table triggers and DDL constraints |
| `is_active` | INTEGER | Yes | — | — | — | NOT NULL; Default 1 |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `employee_pay_group_assignments`

Effective-dated employee-to-pay-group bridge; end dates are exclusive.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `assignment_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `employee_id` | INTEGER | Yes | — | — | UNIQUE(employee_id, effective_from) | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `pay_group_id` | INTEGER | Yes | — | — | — | FK → pay_groups.pay_group_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `effective_from` | TEXT | Yes | — | ISO-8601 date; inclusive | UNIQUE(employee_id, effective_from) | NOT NULL; ISO date and chronological interval checks where applicable |
| `effective_to` | TEXT | No | — | ISO-8601 date; exclusive | — | ISO date and chronological interval checks where applicable |
| `status` | TEXT | Yes | scheduled \| active \| ended \| cancelled | — | — | NOT NULL; Default 'active'; CHECK/trigger restricts the allowed values listed |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `created_by` | TEXT | Yes | — | — | — | NOT NULL; Default 'system' |
| `notes` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |

## `employees`

Employee identity, employment lifecycle, compensation and current pay-group reference.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `employee_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `employee_number` | TEXT | Yes | — | — | UNIQUE(employee_number) | NOT NULL |
| `first_name` | TEXT | Yes | — | — | — | NOT NULL |
| `last_name` | TEXT | Yes | — | — | — | NOT NULL |
| `email` | TEXT | Yes | — | — | UNIQUE(email) | NOT NULL |
| `department` | TEXT | Yes | — | — | — | NOT NULL |
| `department_id` | INTEGER | Yes | — | — | — | FK → departments.department_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `job_title` | TEXT | Yes | — | — | — | NOT NULL |
| `hire_date` | TEXT | Yes | — | ISO-8601 calendar date | — | NOT NULL |
| `termination_date` | TEXT | No | — | ISO-8601 calendar date | — | No additional field-level check; see table triggers and DDL constraints |
| `pay_group_id` | INTEGER | Yes | — | — | — | FK → pay_groups.pay_group_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `employment_status` | TEXT | Yes | active \| terminated \| on_leave | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `standard_hours` | REAL | Yes | — | hours per week | — | NOT NULL; Default 40; Non-negative numeric constraint |
| `annual_salary` | REAL | Yes | — | currency units per year | — | NOT NULL; Non-negative numeric constraint |
| `hourly_rate` | REAL | Yes | — | currency units per hour | — | NOT NULL; Non-negative numeric constraint |
| `bank_account_token` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `tax_info_token` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `exception_assignments`

Append-only exception assignment events.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `assignment_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `exception_id` | INTEGER | Yes | — | — | — | FK → exceptions.exception_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `assignee_id` | TEXT | Yes | — | — | — | NOT NULL |
| `assignee_role` | TEXT | Yes | Employee \| Manager \| HR Partner \| IT/Operations Partner \| System Administrator | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `assigned_by` | TEXT | Yes | — | — | — | NOT NULL |
| `assigned_by_role` | TEXT | Yes | Employee \| Manager \| HR Partner \| IT/Operations Partner \| System Administrator | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `assigned_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `comments` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |

## `exception_review_history`

Append-only exception review events.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `review_action_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `exception_id` | INTEGER | Yes | — | — | — | FK → exceptions.exception_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `reviewer_id` | TEXT | Yes | — | — | — | NOT NULL |
| `reviewer_role` | TEXT | Yes | Employee \| Manager \| HR Partner \| IT/Operations Partner \| System Administrator | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `previous_status` | TEXT | Yes | open \| under_review \| resolved \| rejected | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `new_status` | TEXT | Yes | open \| under_review \| resolved \| rejected | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `action_timestamp` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `comments` | TEXT | Yes | — | — | — | NOT NULL |

## `exceptions`

Validation findings, references, severity and resolution lifecycle.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `exception_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `exception_code` | TEXT | Yes | — | — | UNIQUE(exception_code) | NOT NULL |
| `finding_key` | TEXT | Yes | — | — | UNIQUE(finding_key) | NOT NULL |
| `anomaly_label` | TEXT | Yes | — | — | — | NOT NULL |
| `payroll_run_id` | INTEGER | Yes | — | — | — | FK → payroll_runs.payroll_run_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `employee_id` | INTEGER | No | — | — | — | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT) |
| `employee_reference` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `pay_period_id` | INTEGER | No | — | — | — | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT) |
| `pay_period_reference` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `entity_type` | TEXT | Yes | — | — | — | NOT NULL |
| `entity_id` | TEXT | Yes | — | — | — | NOT NULL |
| `rule_code` | TEXT | Yes | — | — | — | NOT NULL |
| `validation_rule_id` | INTEGER | No | — | — | — | FK → validation_rules.validation_rule_id (ON UPDATE/DELETE RESTRICT) |
| `severity` | TEXT | Yes | info \| warning \| critical | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `message` | TEXT | Yes | — | — | — | NOT NULL |
| `expected_value` | TEXT | No | — | JSON/text value (rule-specific) | — | No additional field-level check; see table triggers and DDL constraints |
| `actual_value` | TEXT | No | — | JSON/text value (rule-specific) | — | No additional field-level check; see table triggers and DDL constraints |
| `details_json` | TEXT | Yes | — | — | — | NOT NULL; Default '{}' |
| `status` | TEXT | Yes | open \| under_review \| resolved \| waived | — | — | NOT NULL; Default 'open'; CHECK/trigger restricts the allowed values listed |
| `workflow_status` | TEXT | Yes | open \| under_review \| resolved \| rejected | — | — | NOT NULL; Default 'open'; CHECK/trigger restricts the allowed values listed |
| `resolution` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `detected_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `last_detected_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `resolved_at` | TEXT | No | — | UTC timestamp | — | No additional field-level check; see table triggers and DDL constraints |

## `leave_records`

Paid/unpaid leave, review status and correction lineage.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `leave_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `employee_id` | INTEGER | Yes | — | — | — | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `pay_period_id` | INTEGER | Yes | — | — | — | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `leave_type` | TEXT | Yes | paid \| unpaid | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `start_date` | TEXT | Yes | — | ISO-8601 calendar date | — | NOT NULL; ISO date and chronological interval checks where applicable |
| `end_date` | TEXT | Yes | — | ISO-8601 calendar date | — | NOT NULL; ISO date and chronological interval checks where applicable |
| `hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `status` | TEXT | Yes | pending \| approved \| rejected \| cancelled | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `supersedes_leave_id` | INTEGER | No | — | — | — | FK → leave_records.leave_id (ON UPDATE/DELETE RESTRICT) |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `pay_groups`

Payroll frequency, currency and calculation policy.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `pay_group_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `code` | TEXT | Yes | — | — | UNIQUE(code) | NOT NULL |
| `name` | TEXT | Yes | — | — | — | NOT NULL |
| `pay_frequency` | TEXT | Yes | monthly \| semi_monthly \| biweekly \| weekly | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `currency` | TEXT | Yes | — | three-letter currency code | — | NOT NULL; Default 'USD' |
| `standard_hours` | REAL | Yes | — | hours per week | — | NOT NULL; Default 40; Non-negative numeric constraint |
| `overtime_multiplier` | REAL | Yes | — | unitless multiplier | — | NOT NULL; Default 1.5 |
| `max_period_hours` | REAL | Yes | — | hours per pay period | — | NOT NULL; Default 200; Non-negative numeric constraint |

## `pay_periods`

Pay calendar periods and lifecycle status.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `pay_period_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `pay_group_id` | INTEGER | Yes | — | — | UNIQUE(pay_group_id, pay_period_code); UNIQUE(pay_group_id, period_start, period_end) | FK → pay_groups.pay_group_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `period_start` | TEXT | Yes | — | ISO-8601 calendar date | UNIQUE(pay_group_id, period_start, period_end) | NOT NULL; ISO date and chronological interval checks where applicable |
| `period_end` | TEXT | Yes | — | ISO-8601 calendar date | UNIQUE(pay_group_id, period_start, period_end) | NOT NULL; ISO date and chronological interval checks where applicable |
| `payment_date` | TEXT | Yes | — | ISO-8601 calendar date | — | NOT NULL; ISO date and chronological interval checks where applicable |
| `pay_period_code` | TEXT | Yes | — | — | UNIQUE(pay_group_id, pay_period_code) | NOT NULL |
| `status` | TEXT | Yes | open \| processing \| validated \| approved \| exported \| closed | — | — | NOT NULL; Default 'open'; CHECK/trigger restricts the allowed values listed |

## `payroll_exports`

Finalized payroll export records; one export per run.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `export_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `payroll_run_id` | INTEGER | Yes | — | — | UNIQUE(payroll_run_id) | FK → payroll_runs.payroll_run_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `file_path` | TEXT | Yes | — | — | — | NOT NULL |
| `format` | TEXT | Yes | csv \| xlsx \| json | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `exported_by` | TEXT | Yes | — | — | — | NOT NULL |
| `exported_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `record_count` | INTEGER | Yes | — | number of exported rows | — | NOT NULL; Non-negative numeric constraint |
| `checksum` | TEXT | No | — | — | — | No additional field-level check; see table triggers and DDL constraints |

## `payroll_inputs`

One source-derived employee/pay-period input aggregate.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `payroll_input_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `payroll_input_code` | TEXT | Yes | — | — | UNIQUE(payroll_input_code) | NOT NULL |
| `employee_id` | INTEGER | Yes | — | — | UNIQUE(employee_id, pay_period_id) | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `pay_period_id` | INTEGER | Yes | — | — | UNIQUE(employee_id, pay_period_id) | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `regular_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `overtime_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `paid_leave_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `allowance_total` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `deduction_total` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |

## `payroll_results`

Calculated result linked one-to-one to its payroll run input.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `payroll_result_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `payroll_run_input_id` | INTEGER | Yes | — | — | UNIQUE(payroll_run_input_id) | FK → payroll_run_inputs.payroll_run_input_id (ON UPDATE/DELETE RESTRICT); NOT NULL; Unique FK; must match the same run and employee |
| `payroll_run_id` | INTEGER | Yes | — | — | UNIQUE(payroll_run_id, employee_id) | FK → payroll_runs.payroll_run_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `employee_id` | INTEGER | Yes | — | — | UNIQUE(payroll_run_id, employee_id) | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `regular_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `overtime_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `regular_pay` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `overtime_pay` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `allowance_total` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `deduction_total` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `gross_pay` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `net_pay` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `calculation_details` | TEXT | Yes | — | — | — | NOT NULL; Default '{}' |

## `payroll_run_inputs`

Per-run employee/period snapshot used by payroll calculation.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `payroll_run_input_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `payroll_run_id` | INTEGER | Yes | — | — | UNIQUE(payroll_run_id, employee_id) | FK → payroll_runs.payroll_run_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `employee_id` | INTEGER | Yes | — | — | UNIQUE(payroll_run_id, employee_id) | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `pay_period_id` | INTEGER | Yes | — | — | — | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `regular_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `overtime_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `paid_leave_hours` | REAL | Yes | — | hours | — | NOT NULL; Non-negative numeric constraint |
| `allowance_total` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |
| `deduction_total` | REAL | Yes | — | currency units | — | NOT NULL; Non-negative numeric constraint |

## `payroll_runs`

Versioned processing runs for a pay period.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `payroll_run_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `pay_period_id` | INTEGER | Yes | — | — | UNIQUE(pay_period_id, run_number) | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `run_number` | INTEGER | Yes | — | — | UNIQUE(pay_period_id, run_number) | NOT NULL |
| `status` | TEXT | Yes | draft \| processed \| validated \| approved \| exported \| failed | — | — | NOT NULL; Default 'draft'; CHECK/trigger restricts the allowed values listed |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |
| `created_by` | TEXT | Yes | — | — | — | NOT NULL; Default 'system' |

## `time_entries`

Employee time submissions, approval status and correction lineage.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `time_entry_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `employee_id` | INTEGER | Yes | — | — | — | FK → employees.employee_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `pay_period_id` | INTEGER | Yes | — | — | — | FK → pay_periods.pay_period_id (ON UPDATE/DELETE RESTRICT); NOT NULL |
| `work_date` | TEXT | Yes | — | ISO-8601 calendar date | — | NOT NULL |
| `time_entry_code` | TEXT | Yes | — | — | UNIQUE(time_entry_code) | NOT NULL |
| `regular_hours` | REAL | Yes | — | hours | — | NOT NULL; Default 0; Non-negative numeric constraint |
| `overtime_hours` | REAL | Yes | — | hours | — | NOT NULL; Default 0; Non-negative numeric constraint |
| `source` | TEXT | Yes | — | — | — | NOT NULL; Default 'synthetic' |
| `status` | TEXT | Yes | draft \| submitted \| approved \| rejected | — | — | NOT NULL; Default 'submitted'; CHECK/trigger restricts the allowed values listed |
| `approval_status` | TEXT | Yes | pending \| approved \| rejected | — | — | NOT NULL; Default 'pending'; CHECK/trigger restricts the allowed values listed |
| `submission_type` | TEXT | Yes | original \| correction \| duplicate | — | — | NOT NULL; Default 'original'; CHECK/trigger restricts the allowed values listed |
| `supersedes_time_entry_id` | INTEGER | No | — | — | — | FK → time_entries.time_entry_id (ON UPDATE/DELETE RESTRICT) |
| `created_at` | TEXT | Yes | — | UTC timestamp | — | NOT NULL; Default CURRENT_TIMESTAMP |

## `validation_rules`

Validation rule catalog and effective dates.

| Field | SQLite type | Required | Allowed values | Units | Unique | Validation rules |
|---|---|---:|---|---|---|---|
| `validation_rule_id` | INTEGER | Yes | — | — | PK | Primary key; updates rejected by immutable-ID trigger |
| `rule_code` | TEXT | Yes | — | — | UNIQUE(rule_code) | NOT NULL |
| `name` | TEXT | Yes | — | — | — | NOT NULL |
| `description` | TEXT | Yes | — | — | — | NOT NULL |
| `severity` | TEXT | Yes | info \| warning \| critical | — | — | NOT NULL; CHECK/trigger restricts the allowed values listed |
| `is_active` | INTEGER | Yes | 0 \| 1 (false \| true) | — | — | NOT NULL; Default 1; CHECK/trigger restricts the allowed values listed |
| `effective_from` | TEXT | Yes | — | ISO-8601 date; inclusive | — | NOT NULL; Default '2026-01-01'; ISO date and chronological interval checks where applicable |
| `effective_to` | TEXT | No | — | ISO-8601 date; exclusive | — | ISO date and chronological interval checks where applicable |

## Cross-field and trigger validations

- Employee department text must match its normalized `department_id` FK.
- Employee/pay-group effective assignment intervals cannot overlap; `effective_to` is exclusive. Existing employees are backfilled from hire/termination dates.
- Source records must reference existing employees/periods in the same pay group; time and leave dates must lie within their period.
- A PayrollRunInput must use the period owned by its PayrollRun. A PayrollResult must reference the matching run input for the same run and employee.
- Approval history must link the same employee/payroll input/pay period as its PayrollRun.
- Exceptions must reference the ValidationRule whose `rule_code` matches the exception.
- PayrollExport is unique per payroll run. Payroll ID and business-code fields are immutable after insert.
- Audit-event entity pointers are polymorphic as noted above; service-level identity/role checks validate reviewer role and action permissions.

Run `python -m payroll_validation.database.init_db` to apply additive migrations and verify the database.
