"""Payroll export interface with a DB-backed fresh-validation gate."""
from payroll_validation.services.payroll_service import export_payroll_run


def export_payroll(run, approval_repository=None, result_repository=None, writer=None, actor="system"):
    if isinstance(run, dict) and run.get("database_path"):
        return export_payroll_run(run["payroll_run_id"],run.get("output_path"),run["database_path"],actor,run.get("format","csv"))
    if run.get("status") != "approved":
        raise ValueError("Payroll must be approved before export")
    if approval_repository is None or not approval_repository.is_approved(run["payroll_run_id"]):
        raise ValueError("Payroll must have a recorded approval before export")
    if exception_repository := run.get("exception_repository"):
        if exception_repository.unresolved_critical(run["payroll_run_id"]):
            raise ValueError("Unresolved critical exceptions block export")
    if result_repository is None or writer is None:
        raise ValueError("An export writer and result repository are required")
    return writer.write(result_repository.list_for_run(run["payroll_run_id"]),actor=actor)
