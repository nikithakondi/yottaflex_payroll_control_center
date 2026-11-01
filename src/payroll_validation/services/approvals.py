"""Payroll approval workflow; DB-backed approval always revalidates first."""
from payroll_validation.services.payroll_service import approve_payroll_run
from payroll_validation.approvals.approval_service import review_payroll_input, submit_source_correction


def approve_run(run, approver, exception_repository=None, approval_repository=None):
    if isinstance(run, dict) and run.get("database_path"):
        return approve_payroll_run(run["payroll_run_id"],approver,run["database_path"])
    if run.get("status") != "validated":
        raise ValueError("Payroll run must be validated before approval")
    blockers=exception_repository.unresolved_critical(run["payroll_run_id"]) if exception_repository else []
    if blockers:
        raise ValueError("Cannot approve payroll with unresolved critical exceptions")
    if approval_repository is None:
        raise ValueError("An approval repository or database-backed run is required")
    return approval_repository.record(run["payroll_run_id"],approver,"approved")
