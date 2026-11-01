"""Deduction management service backed by SQLite."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.records import create_deduction

record_deduction=create_deduction
def list_deductions(database_path=DATABASE_PATH,pay_period_id=None):
    sql="SELECT * FROM deductions"; params=()
    if pay_period_id is not None: sql+=" WHERE pay_period_id=?"; params=(pay_period_id,)
    with connect(database_path) as db: return [dict(r) for r in db.execute(sql+" ORDER BY deduction_id DESC",params)]
