# Architecture

The application uses a layered design: Streamlit pages render workflows; service modules coordinate business operations; repositories encapsulate SQL persistence; SQLite stores operational and audit records. Payroll processing, validation rules, approval and export are separate steps so results can be explained and tested.

## Lifecycle

Maintain employee and pay configuration → capture time, leave and adjustments → process a payroll run → validate and create exceptions → resolve findings → approve the run → export → inspect audit history.

An export requires approval. Approval is blocked when critical exceptions remain unresolved. Every material change should emit an append-only audit event. UI pages should not implement calculation rules or issue ad-hoc writes.

## Synthetic data

The generator uses seed `20261022`, targets 3,000 employees and three monthly periods. The full profile defines its 100,000 transaction count as final persisted `time_entries + allowances + deductions`, including corrections, duplicate submissions, pending/rejected time, and four planted source-anomaly rows. Leave, payroll snapshots/results, audit records and ground truth are excluded. The manifest records this definition and per-table counts. `ground_truth.csv` and `ground_truth.json` are separate expected-output artifacts and are never payroll input. Leave correction lineage is persisted in `leave_records`; synthetic eligibility is deterministic and payroll totals include eligible rows only.
