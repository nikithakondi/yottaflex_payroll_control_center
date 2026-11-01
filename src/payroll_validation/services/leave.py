"""Leave management service backed by SQLite."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.records import create_leave_record

record_leave=create_leave_record
def list_leave(database_path=DATABASE_PATH,pay_period_id=None):
    sql="SELECT * FROM leave_records"; params=()
    if pay_period_id is not None: sql+=" WHERE pay_period_id=?"; params=(pay_period_id,)
    with connect(database_path) as db: return [dict(r) for r in db.execute(sql+" ORDER BY start_date DESC",params)]
