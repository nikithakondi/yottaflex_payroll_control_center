"""Shared project configuration."""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
EXPORT_DIR = PROJECT_ROOT / "exports"
DATABASE_PATH = Path(os.environ.get("YOTTAFLEX_DATABASE_PATH", DATA_DIR / "payroll.db"))
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.csv"
RANDOM_SEED = 20261022
SYNTHETIC_EMPLOYEE_COUNT = 3_000
PAY_PERIOD_COUNT = 3
TARGET_TRANSACTION_RECORDS = 100_000
