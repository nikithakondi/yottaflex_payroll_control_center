"""Compatibility exports for the payroll processing service."""
from payroll_validation.services.payroll_service import (
    approve_payroll_run, export_payroll_run, process_payroll_period, record_time_correction,
    record_leave_correction, record_allowance_correction, record_deduction_correction,
)


def process_payroll(pay_period_id, run_repository=None, calculation_service=None):
    """Legacy direct entry point; repository adapters are no longer required."""
    if run_repository is None:
        return process_payroll_period(pay_period_id)
    run=run_repository.create(pay_period_id)
    results=calculation_service.calculate_period(pay_period_id)
    run_repository.save_results(run["payroll_run_id"],results)
    return run
