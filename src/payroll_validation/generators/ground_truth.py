"""Ground-truth CSV contract and writer (reference only, never validator input)."""
from payroll_validation.config import GROUND_TRUTH_PATH
from payroll_validation.generators.anomaly_generator import (
    GROUND_TRUTH_COLUMNS,
    write_ground_truth as _write_ground_truth,
    write_ground_truth_json as _write_ground_truth_json,
)

__all__ = ["GROUND_TRUTH_COLUMNS", "GROUND_TRUTH_PATH", "write_ground_truth", "write_ground_truth_json"]


def write_ground_truth(rows, path=GROUND_TRUTH_PATH):
    """Write the anomaly reference CSV to the configured separate data path."""
    return _write_ground_truth(rows, path)


def write_ground_truth_json(rows, path=None):
    """Write the independent ground-truth contract as JSON."""
    if path is None:
        path = GROUND_TRUTH_PATH.with_suffix(".json")
    return _write_ground_truth_json(rows, path)
