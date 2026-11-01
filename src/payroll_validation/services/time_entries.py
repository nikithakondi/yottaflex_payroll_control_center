"""Time entry submission, review and query operations."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.records import create_time_entry, set_time_approval

def list_period_entries(repository, pay_period_id=None):
    if hasattr(repository,"list_by_period"): return repository.list_by_period(pay_period_id)
    path=repository if isinstance(repository,(str,bytes)) else DATABASE_PATH
    with connect(path) as db: return [dict(r) for r in db.execute("SELECT * FROM time_entries WHERE pay_period_id=? ORDER BY work_date,time_entry_id",(pay_period_id,))]
