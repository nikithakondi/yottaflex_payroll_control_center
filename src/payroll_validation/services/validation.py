"""Compatibility exports for payroll validation service functions."""
from payroll_validation.validators.validation_service import validate_all_payroll_runs, validate_payroll_run


def validate_payroll(payroll_run, rules=None, exception_service=None):
    """Legacy entry point; prefer validate_payroll_run(run_id, database_path)."""
    if isinstance(payroll_run, dict):
        payroll_run_id=payroll_run.get("payroll_run_id")
        database_path=payroll_run.get("database_path")
    else:
        payroll_run_id=payroll_run
        database_path=None
    if payroll_run_id is None:
        raise ValueError("payroll_run_id is required")
    if database_path is None:
        return validate_payroll_run(payroll_run_id)
    return validate_payroll_run(payroll_run_id,database_path)
