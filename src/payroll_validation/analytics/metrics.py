"""Dashboard metric transformations."""
def exception_rate(exception_count, employee_count):
    return exception_count / employee_count if employee_count else 0.0
