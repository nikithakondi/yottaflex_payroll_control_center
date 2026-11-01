from payroll_validation.generators.ground_truth import GROUND_TRUTH_COLUMNS
from payroll_validation.generators.anomaly_generator import ANOMALY_RULES

def test_ground_truth_contains_anomaly_validation_contract():
    assert {"anomaly_id", "employee_id", "pay_period_id", "issue_type", "expected_validation_result", "expected_decision"}.issubset(GROUND_TRUTH_COLUMNS)
    assert {rule[0] for rule in ANOMALY_RULES} == {
        "HOURS_PERIOD_MAX", "DUPLICATE_ALLOWANCE", "TIME_UNAPPROVED",
        "DUP_UNPAID_LEAVE_DEDUCTION", "PAYROLL_RECONCILIATION",
    }
