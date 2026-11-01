"""SQLite connection helpers with foreign-key enforcement."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from payroll_validation.config import DATABASE_PATH


@contextmanager
def connect(path=DATABASE_PATH):
    """Yield a row-aware SQLite connection with FK checks and transaction handling."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
