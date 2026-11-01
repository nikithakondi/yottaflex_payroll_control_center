# Business Rules

## Payroll calculation

1. Only active employees assigned to the pay group's monthly calendar receive payroll run inputs.
2. Effective time includes approved regular/overtime hours. A superseded time row is excluded once an approved correction row exists. Pending/rejected time is never paid and causes a validation finding when submitted for the run.
3. Approved paid leave hours are paid at the employee hourly rate. Unpaid leave is not added to hours/pay; generation creates a linked deduction equal to hourly rate × approved unpaid leave hours.
4. Effective allowances with `eligible=1` are included; ineligible allowances stay visible but do not increase pay. The synthetic profile defaults generated allowances to eligible.
5. Effective deductions reduce net pay. A correction row replaces its linked predecessor for calculations; unpaid leave must have exactly one effective linked deduction.
6. `regular_pay = (approved regular hours + approved paid leave hours) × hourly_rate`.
7. `overtime_pay = approved overtime hours × hourly_rate × pay-group overtime multiplier`.
8. `gross_pay = regular_pay + overtime_pay + eligible allowances`.
9. `net_pay = gross_pay − effective deductions`.
10. Calculated money rounds half-up to two decimal places. Each run stores source aggregates and calculation details. Reconciliation recalculates from source data and compares stored inputs, components, gross, and net.

## Validation and exception handling

Validation checks missing bank details/tax information, duplicate effective time entries, period maximum hours, duplicate allowance source references, unapproved time, duplicate unpaid-leave deductions, incorrect payroll inputs/components, gross/net reconciliation, invalid employee/period relationships, and time/leave dates outside their linked period. Rules are catalogued in `validation_rules`; all current rules are critical and active by default.

Finding records are deduplicated by a stable finding key, receive a `PEX-2026-######` code, contain a validation-rule link and employee/period references when available, and are audited. Workflow states are Open, Under Review, Resolved, and Rejected. Open, Under Review, or Rejected critical findings block approval and export. A repeated finding reopens during validation; a finding that no longer exists can be resolved by revalidation. A comment-only resolution does not alter source data or substitute for a successful revalidation.

## Approval and correction

Manager and HR Partner may approve, reject, or request correction. Employee may submit a correction only for their own record. IT/Operations Partner may review technical exception categories, and System Administrator can administer assignments/reviews; neither role approves payroll. Invalid payroll and unresolved critical exceptions cannot be approved. Each decision produces an immutable `approval_history` and audit event.

Time, leave, allowance, and deduction corrections append new rows that point to the source version. They never update or delete the original. Corrections create a fresh payroll run and must be revalidated before review/approval proceeds. Previous runs and previous decisions remain queryable.

## Export

CSV and JSON exports are available only after a fresh validation, successful reconciliation, a run-level approval, and approved status on every payroll input. A critical unresolved exception blocks export. One export per run is allowed. The export history includes the file path, format, record count, checksum, actor, and time.
