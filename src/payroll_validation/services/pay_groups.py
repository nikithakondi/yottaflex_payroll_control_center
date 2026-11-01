"""Pay group management service backed by SQLite."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.records import create_pay_group as _create

def create_pay_group(repository,pay_group=None):
    if hasattr(repository,"create"): return repository.create(pay_group)
    values=repository if pay_group is None else pay_group
    return _create(values,repository if isinstance(repository,(str,bytes)) else DATABASE_PATH)

def list_pay_groups(database_path=DATABASE_PATH):
    with connect(database_path) as db: return [dict(r) for r in db.execute("SELECT * FROM pay_groups ORDER BY code")]
