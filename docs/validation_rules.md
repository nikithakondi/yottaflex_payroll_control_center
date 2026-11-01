# Validation rules and business controls

Rules should have stable codes, severity, a clear message, source references and tests. Initial rule catalog:

| Code | Check |
| --- | --- |
| BANK_DETAILS_MISSING | Active employee lacks bank account details |
| TAX_INFORMATION_MISSING | Active employee lacks tax information |
| DUPLICATE_TIME_ENTRY | More than one active approved time entry exists for an employee/date |
| HOURS_PERIOD_MAX | Effective approved hours exceed the pay group's configured period maximum |
| DUPLICATE_ALLOWANCE | A source allowance submission is duplicated |
| TIME_UNAPPROVED | Pending or otherwise unapproved time would be included in payroll |
| DUP_UNPAID_LEAVE_DEDUCTION | An approved unpaid leave has more than one linked deduction |
| INCORRECT_PAYROLL_CALCULATION | Run input snapshots or calculated pay components differ from source-derived values |
| PAYROLL_RECONCILIATION | Gross or net payroll totals do not reconcile to their components |
| INVALID_REFERENCE | Employee, pay-period or related source references are invalid or inconsistent |
| DATE_OUTSIDE_PERIOD | Time-entry and leave dates fall outside the linked pay period |

The synthetic generator injects five labeled examples after valid baseline records: period hours above the configured maximum, a duplicated allowance source submission, pending/unapproved time, a duplicate deduction linked to approved unpaid leave, and a payroll result whose gross total no longer reconciles to its components. Their expected validation labels and decisions are stored in separate `ground_truth.csv` and `ground_truth.json` artifacts; the validation engine does not read either file. Tests read them only after running validation and compare the expected issues to persisted exceptions.

Do not silently repair source data. Findings become exceptions. Critical unresolved exceptions block approval; an approved payroll run is required before export. Record exception resolution and approval/export actions in audit history.
