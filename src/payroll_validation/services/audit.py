"""Append-only audit history read/write operations."""
import json
from payroll_validation.config import DATABASE_PATH
from payroll_validation.database.connection import connect

def record_event(repository, entity_type, entity_id, action, actor, before=None, after=None):
    if hasattr(repository,"append"): return repository.append(entity_type,entity_id,action,actor,before,after)
    path=repository if isinstance(repository,str) else DATABASE_PATH
    with connect(path) as db:
        db.execute("INSERT INTO audit_events(entity_type,entity_id,action,actor,before_json,after_json) VALUES (?,?,?,?,?,?)",
                   (entity_type,str(entity_id),action,str(actor),json.dumps(before,default=str) if before is not None else None,json.dumps(after,default=str) if after is not None else None))
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

def list_events(database_path=DATABASE_PATH,entity_type=None,entity_id=None,limit=1000):
    clauses=[]; params=[]
    if entity_type: clauses.append("entity_type=?"); params.append(entity_type)
    if entity_id is not None: clauses.append("entity_id=?"); params.append(str(entity_id))
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    with connect(database_path) as db:
        return [dict(r) for r in db.execute("SELECT * FROM audit_events"+where+" ORDER BY audit_event_id DESC LIMIT ?",(*params,int(limit)))]
