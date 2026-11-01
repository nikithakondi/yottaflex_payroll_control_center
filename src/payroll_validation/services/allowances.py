"""Allowance management service backed by SQLite."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.records import create_allowance

record_allowance=create_allowance
def list_allowances(database_path=DATABASE_PATH,pay_period_id=None):
    sql="SELECT * FROM allowances"; params=()
    if pay_period_id is not None: sql+=" WHERE pay_period_id=?"; params=(pay_period_id,)
    with connect(database_path) as db: return [dict(r) for r in db.execute(sql+" ORDER BY allowance_id DESC",params)]
