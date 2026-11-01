# Assumptions and Scope

* The challenge dataset uses one monthly USD pay group and pay periods January–March 2026.
* The generated employees are hourly for calculation purposes. Annual salaries are synthetic and converted to hourly rates by annual salary / 2,080.
* Every generated allowance is eligible by default. The schema supports ineligible rows; no jurisdiction-specific taxability/eligibility rules are inferred from the `taxable` flag.
* Approved paid leave hours are paid at the base hourly rate. Approved unpaid leave creates a deduction equal to base hourly rate × leave hours. This is a challenge demonstration policy, not legal/payroll advice.
* Employee bank information is a Faker-generated token/IBAN-style test value. It is not connected to a real financial account. Tax tokens are synthetic.
* The application's SQLite tables are the source of truth. CSV snapshots are reproducibility/readability artifacts; ground truth is used only by tests.
* Local Streamlit role selectors demonstrate workflow service permissions. There is no login, identity verification, directory integration, or manager-to-employee scope relation.
* All current validation catalog rules use critical severity so known data integrity failures block approval/export. A production policy may classify some findings differently after review.
* Database amounts are SQLite REAL and are rounded to two decimals in the calculation service; a production payroll platform should use integer minor units or Decimal storage and currency-specific policies.
* Corrections are append-only and supersession affects effective calculation rows. Historical records and payroll runs are retained.
* CSV/JSON artifacts remain local. Production storage, access controls, retention periods, backup, and encryption are deployment responsibilities.
