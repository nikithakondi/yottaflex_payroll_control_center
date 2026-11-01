"""Read-only analytics queries for dashboard views."""
from payroll_validation.database.connection import connect

def payroll_totals(path=None):
    """Return payroll totals; an empty result is valid before processing."""
    with connect(path) if path else connect() as db:
        return db.execute("SELECT COUNT(*) AS result_count, COALESCE(SUM(gross_pay),0) AS gross_pay, COALESCE(SUM(net_pay),0) AS net_pay FROM payroll_results").fetchone()
