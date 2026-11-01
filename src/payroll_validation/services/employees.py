"""Employee management service backed by the SQLite employee/pay-group tables."""
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect
from payroll_validation.services.records import create_employee as _create, update_employee

def create_employee(repository, employee=None):
    if hasattr(repository,"create"): return repository.create(employee)
    values=repository if employee is None else employee
    return _create(values,repository if isinstance(repository,(str,bytes)) else DATABASE_PATH)

def list_employees(database_path=DATABASE_PATH, search=None, limit=1000):
    sql="SELECT * FROM employees"; params=()
    if search: sql+=" WHERE employee_number LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR email LIKE ?"; params=(f"%{search}%",)*4
    with connect(database_path) as db: return [dict(r) for r in db.execute(sql+" ORDER BY employee_number LIMIT ?",(*params,int(limit)))]

def change_employee(employee_id, changes, database_path=DATABASE_PATH, actor="system"):
    return update_employee(employee_id,changes,database_path,actor)
