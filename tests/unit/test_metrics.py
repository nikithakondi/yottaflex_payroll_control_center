from payroll_validation.analytics.metrics import exception_rate

def test_exception_rate_handles_empty_population():
    assert exception_rate(0, 0) == 0.0

def test_exception_rate_calculates_ratio():
    assert exception_rate(3, 30) == 0.1
