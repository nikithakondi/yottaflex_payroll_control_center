# YottaFlex AI — Payroll Validation and Reconciliation System

A locally runnable payroll control application for preparing payroll from source records, validating calculations, resolving exceptions, recording approvals, and exporting approved payroll. It uses Python, SQLite/SQL, Pandas, Streamlit, Plotly, Faker, Pytest, and openpyxl for Excel workbooks. It does not require paid cloud services.

## Problem statement

Payroll errors can arise from unapproved or duplicate time, leave deductions applied more than once, duplicate allowances, missing employee banking or tax data, and calculations that do not reconcile. The application keeps source records, versioned payroll runs, validation findings, human decisions, exports, and audit events together in a relational SQLite database so reviewers can trace why a payroll run is ready or blocked.

## Objectives and workflow

Maintain employees and pay calendars → capture time, leave, allowances, and deductions → process a versioned payroll run → validate every run against source data → assign and resolve exceptions → approve valid payroll inputs → export once as CSV, JSON, or Excel → review audit and reconciliation reports.

Corrections create new linked rows. Previous source rows, runs, approvals, exception reviews, and export history remain available. `ground_truth.csv` and `ground_truth.json` are independent generator/test artifacts and are never loaded by the validation engine.

## Architecture

* `src/payroll_validation/database/`: SQLite schema, connection management, migrations, and integrity verification.
* `src/payroll_validation/generators/`: deterministic master data, transaction data, anomaly injection, and separate ground truth.
* `src/payroll_validation/services/`: database-backed employee/pay calendar/source management, payroll calculation, reconciliation, exceptions, and audit operations.
* `src/payroll_validation/validators/`, `approvals/`, and `exports/`: payroll validation, manager/HR approval, and CSV/JSON/Excel report exports.
* `src/payroll_validation/analytics/` and `dashboard/`: dashboard queries, metrics, Plotly charts, and Streamlit page renderers. `ui/` and former service import paths remain thin compatibility shims.
* `pages/`: 15 application navigation pages.
* `tests/`: unit, data-contract, and integration tests.
* `docs/`: schema, data dictionary, business rules, assumptions, architecture, and validation documentation.
* `reports/`: generated validation, reconciliation, and exception CSV snapshots.
* `prompts/AI_PROMPTS.md` and root `AI_PROMPTS.md`: staged AI prompt history.

### Project layout

```text
YottaFlex-Payroll-Validation/
├── data/
│   ├── input/
│   ├── generated/
│   │   ├── starter/
│   │   ├── full/
│   │   └── full_verified_v2/   # latest validated full snapshot; prior snapshots retained
│   ├── ground_truth.csv
│   ├── ground_truth.json
│   └── payroll.db
├── docs/                       # DATA_DICTIONARY, DATABASE_SCHEMA, BUSINESS_RULES, ASSUMPTIONS
├── reports/                    # validation, reconciliation, exception CSVs
├── src/payroll_validation/
│   ├── database/ generators/ models/ services/
│   ├── validators/ approvals/ exports/ dashboard/ analytics/
├── tests/                       # database, generator, validation, payroll, approvals, exports
├── pages/                       # 15 Streamlit navigation pages
├── app.py
├── main.py
├── requirements.txt
├── README.md
├── AI_PROMPTS.md
└── .gitignore
```

SQLite uses integer primary keys for joins and immutable human-readable business codes for IDs, including `EMP-000001`, `PP-2026-01`, `TIME-EMP-000001-2026-01-02`, `PIN-EMP-000001-2026-01`, and `PEX-2026-000001`.

## Technology stack

| Technology | Use |
| --- | --- |
| Python | Application, generation, and business services |
| SQLite and SQL | Relational storage, constraints, triggers, and queries |
| Pandas | Dashboard/report data frames and tabular downloads |
| Streamlit | Local HR/payroll application |
| Plotly | Interactive payroll and exception charts |
| Faker | Reproducible synthetic employee names and bank tokens |
| Pytest | Automated unit and integration verification |

## Installation

Python 3.10 or newer is required. Run these commands from the project root.

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

If PowerShell blocks activation, use `.venv\Scripts\python.exe` directly for the commands below.

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Database setup and data generation

Initialize and verify the local database:

```bash
python -m payroll_validation.database.init_db
```

Generate the full profile (3,000 employees, three monthly periods, and exactly 100,000 combined time, allowance, and deduction rows):

```bash
python -m payroll_validation.generators.generate_dataset --profile full --replace-existing
```

To keep a separate full-scale snapshot instead of replacing the app database, provide another database and output directory:

```bash
python -m payroll_validation.generators.generate_dataset --profile full --database data/generated/full_submission/payroll.db --output-dir data/generated/full_submission
```

The full profile is the default and uses the app database at `data/payroll.db`; its snapshots are written to `data/generated/full_current/`. Existing employee data is protected from accidental overwrite. Back up `data/payroll.db` before using `--replace-existing`. Use `--profile starter` only for the small 100-employee test fixture. Both profiles use seed `20261022` by default. Use `--seed`, `--database`, and `--output-dir` to select a different deterministic seed or output location. Each profile writes table CSV snapshots, ground-truth CSV and JSON, and a manifest. The full profile also writes `payroll_dataset.xlsx` with one worksheet per database table.

The full profile defines its 100,000 transaction target as the **final persisted row count** of `time_entries + allowances + deductions`. It includes approved, pending/rejected, correction and duplicate submissions, and the four planted source-anomaly rows. It excludes leave rows, payroll inputs/results, audit events and the separate `ground_truth.csv`. For seed `20261022`, the full profile writes 36,542 time entries, 31,729 allowances and 31,729 deductions. The generator writes this definition and category counts to `manifest.json`, and raises an error if the final count is not exactly 100,000. Leave corrections are stored separately in `leave_records` and do not affect the transaction target.

The retained `data/generated/full_100k/` and `data/generated/full_verified_v2/` directories are historical snapshots. The app uses `data/payroll.db` by default; alternatively set `YOTTAFLEX_DATABASE_PATH` to open another database.

Generate report snapshots from the verified full database with `python -m payroll_validation.exports.write_reports --database data/generated/full_verified_v2/payroll.db`. Files are written to `reports/`; the command accepts `--output-dir` to write them elsewhere.

The current schema has 21 tables, 39 foreign-key relationships, and 37 indexes. The 12 required entities are supported by department, effective-dated employee/pay-group assignment, payroll run/snapshot/result, and workflow/audit history tables. Employee departments are normalized in `departments` and linked by foreign key; legacy `department` text is retained for readable reporting. Existing database files were migrated additively with pre-migration backups retained under `.schema_migration_work/pre_migration/`.

## Run the application

```bash
streamlit run app.py
```

By default, the app opens `data/payroll.db` (the full 3,000-employee dataset after full generation). To open another dataset on Windows PowerShell, set the database path in the same terminal before starting Streamlit:

```powershell
$env:YOTTAFLEX_DATABASE_PATH = "data/generated/full_current/payroll.db"
streamlit run app.py
```

On macOS/Linux, use `YOTTAFLEX_DATABASE_PATH=data/generated/full_verified_v2/payroll.db streamlit run app.py`. This setting applies to database-backed pages and payroll export; it does not change or copy either database.

The sidebar contains Dashboard, Employees, Pay Groups, Pay Periods, Time Entries, Leave Management, Allowances, Deductions, Payroll Processing, Validation, Exceptions, Approvals, Payroll Export, Audit History, and Reports & Reconciliation. Forms submit to database-backed service functions; the tables and charts query the configured SQLite database.

The demo is local and has no identity provider. Workflow service calls enforce the selected role permissions, but the Streamlit role/reviewer fields are demo identity inputs and are not authentication.

## Payroll calculations and business rules

For this synthetic monthly hourly-pay model, basic worked pay is regular hours (including approved paid leave hours) multiplied by the employee hourly rate; overtime is paid at the pay group multiplier. Gross pay is regular pay + overtime pay + eligible allowances. Net pay is gross pay − eligible source deductions. Approved unpaid leave is represented by a linked deduction computed as hourly rate × approved unpaid leave hours; its source deduction is included once. Pending time and unapproved leave are not included. See [BUSINESS_RULES.md](BUSINESS_RULES.md) and [ASSUMPTIONS.md](ASSUMPTIONS.md) for rounding and scope details.

The engine checks all five planted scenarios (period hours over maximum, duplicate allowance submission, unapproved time, duplicate unpaid-leave deduction, and payroll reconciliation failure) plus missing bank/tax data, duplicate time, incorrect calculations, and invalid employee/pay-period references. Critical unresolved findings block approval and export. A correction creates a new source record and payroll run, which must be revalidated.

## Payroll export

1. Process a pay period from current source records.
2. Run validation and resolve findings.
3. Review and approve all payroll inputs through Approvals (Manager or HR Partner).
4. Open Payroll Export, select the approved run and CSV, JSON, or Excel, and create the export.
5. Download the generated file. The app records its format, path, row count, checksum, and timestamp in `payroll_exports`; a run cannot be exported twice.

Exports are saved under `exports/` by default. For service-level use, call `export_payroll_run(run_id, output_format="xlsx")`; CSV and JSON are also supported. The Validation page downloads exception reports in CSV or Excel, and Reports downloads employee-level expected/actual reconciliation reports in CSV or Excel.

## Testing

```bash
python -m pytest -q
```

Tests cover database schema and foreign keys, seeded generation and ground-truth contract, all validation rules, exception/approval controls, append-only corrections for all four source record types, reconciliation, export restrictions, CSV/JSON/XLSX output, downloadable validation/reconciliation reports, and metrics. Run `python -m pytest -q` for the current suite.

## Sample outputs

The generator writes `manifest.json` with the seed, profile, row counts, foreign-key count, planted anomaly IDs, and SQLite integrity result. Payroll exports include employee and pay period identifiers, hours, pay components, gross pay, deductions, and net pay. The Reports page shows run-level reconciliation findings and period totals.

## Screenshots

Capture the Dashboard, Validation, Exceptions/Approvals, and Payroll Export screens after running the local app. Store submission screenshots in `docs/screenshots/` and link them here before publishing.

## Limitations

* The local demo uses synthetic identities and deterministic reference tokens; it is not a production payroll processor.
* Streamlit reviewer identity fields demonstrate service-level roles but do not authenticate users or establish manager-to-employee organizational scope.
* The current sample uses one monthly USD pay group. Multi-currency tax law, statutory rules, benefits eligibility, and jurisdiction-specific gross-to-net calculations require country-specific policy and review.
* Numeric values are rounded to two decimal places in the calculation service. A production deployment should use integer minor units or currency-aware Decimal throughout persistence and reporting.
* Export files are written locally and should be handled as sensitive payroll artifacts in real use.

## Future enhancements

Add authenticated users and manager scope, employee/pay-group assignment history, configurable jurisdiction rules, document-backed evidence, configurable payroll calendars, controlled source-file imports, richer approval routing, operational backups, and polished screenshot/demo assets.

## AI usage disclosure

AI tools assisted with architecture review, implementation suggestions, code changes, debugging, tests, and documentation. The project owner must review and understand all code, verify results, and update the prompt history with any further AI use. The recorded prompts are in [prompts/AI_PROMPTS.md](prompts/AI_PROMPTS.md) and the root [AI_PROMPTS.md](AI_PROMPTS.md).

## GitHub submission preparation

Before submitting, rerun the tests, initialize the schema, generate or verify the full profile, check that no real employee/payment details or secrets are present, and commit source, tests, documentation, and the separate test ground truth. SQLite databases and `exports/` are ignored by Git; regenerate the databases using the instructions above.
