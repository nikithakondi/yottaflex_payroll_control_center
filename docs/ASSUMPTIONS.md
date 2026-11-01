# Assumptions and Scope

* The challenge dataset uses one monthly USD pay group and pay periods January–March 2026.
* The generated employees are hourly for calculation purposes. Annual salaries are synthetic and converted to hourly rates by annual salary / 2,080.
* Synthetic allowance and deduction eligibility is explicitly represented by `eligible` and is deterministic: home-office allowances are ineligible when the employee's numeric ID is divisible by four; student-loan deductions are eligible only when the ID is divisible by three; other generated deductions are eligible. Payroll totals include eligible source rows only. These synthetic rules demonstrate eligibility handling and are not jurisdiction or benefit-plan rules.
* Approved paid leave hours are paid at the base hourly rate. Approved unpaid leave creates a deduction equal to base hourly rate × leave hours. This is a challenge demonstration policy, not legal/payroll advice.
* Employee bank information is a Faker-generated token/IBAN-style test value. It is not connected to a real financial account. Tax tokens are synthetic.
* The application's SQLite tables are the source of truth. CSV snapshots are reproducibility/readability artifacts; ground truth is used only by tests.
* Local Streamlit role selectors demonstrate workflow service permissions. There is no login, identity verification, directory integration, or manager-to-employee scope relation.
* All current validation catalog rules use critical severity so known data integrity failures block approval/export. A production policy may classify some findings differently after review.
* Database amounts are SQLite REAL and are rounded to two decimals in the calculation service; a production payroll platform should use integer minor units or Decimal storage and currency-specific policies.
* Corrections are append-only and supersession affects effective calculation rows. Historical records and payroll runs are retained.
* Leave lifecycle statuses are assigned deterministically from the ordered employee-period sequence (not from random draws); generated dates and monetary source amounts use the fixed seed. A paid-leave correction halves the original approved hours, links to the original, and leaves the original row intact.
* The full 100,000 transaction target counts final persisted `time_entries + allowances + deductions`, including correction/duplicate submissions and planted source anomalies. Leave, payroll, audit, and ground-truth rows are excluded.
* CSV/JSON artifacts remain local. Production storage, access controls, retention periods, backup, and encryption are deployment responsibilities.
