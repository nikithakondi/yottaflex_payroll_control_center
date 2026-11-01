"""Pay period management service interface."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.records import create_pay_period as _create

def create_pay_period(repository, period=None):
    values=repository if period is None else period
    if values["period_end"] < values["period_start"]: raise ValueError("Pay period end must not precede its start")
    if hasattr(repository,"create"): return repository.create(values)
    return _create(values,repository if isinstance(repository,(str,bytes)) else DATABASE_PATH)

def list_pay_periods(database_path=DATABASE_PATH):
    with connect(database_path) as db: return [dict(r) for r in db.execute("SELECT p.*,g.code AS pay_group_code FROM pay_periods p JOIN pay_groups g USING(pay_group_id) ORDER BY period_start DESC")]
