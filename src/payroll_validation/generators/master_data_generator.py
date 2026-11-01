"""Deterministic generation of pay groups, employees and monthly periods."""
import calendar
import math
import random
from datetime import date

from faker import Faker

from payroll_validation.config import RANDOM_SEED, SYNTHETIC_EMPLOYEE_COUNT

PAY_GROUPS = (
    {"code": "PG-MONTHLY-01", "name": "YottaFlex Monthly", "pay_frequency": "monthly"},
)
DEPARTMENTS = ("Finance", "Engineering", "Operations", "Customer Support", "Human Resources", "Sales")
JOB_TITLES = ("Analyst", "Associate", "Specialist", "Manager", "Engineer", "Coordinator", "Director")


def generate_master_data(employee_count=SYNTHETIC_EMPLOYEE_COUNT, seed=RANDOM_SEED, year=2026, month_count=3):
    """Return deterministic master rows. IDs are assigned during database insertion."""
    if employee_count < 1:
        raise ValueError("employee_count must be positive")
    if month_count < 1 or not 1 <= year <= 9998 or month_count > 12:
        raise ValueError("month_count must be 1..12 and year must be a valid calendar year")

    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    groups = [
        {**row, "currency": "USD", "standard_hours": 40.0,
         "overtime_multiplier": 1.5, "max_period_hours": 200.0}
        for row in PAY_GROUPS
    ]
    employees = []
    for number in range(1, employee_count + 1):
        # A log-normal distribution creates a broad, right-skewed pay range.
        annual_salary = round(min(220_000, max(28_000, rng.lognormvariate(math.log(72_000), 0.42))), 2)
        group = rng.choice(PAY_GROUPS)
        employees.append({
            "employee_number": f"EMP-{number:06d}",
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "email": f"employee{number:06d}@example.test",
            "department": rng.choice(DEPARTMENTS),
            "job_title": rng.choice(JOB_TITLES),
            "hire_date": date(rng.randint(2017, 2025), rng.randint(1, 12), rng.randint(1, 28)).isoformat(),
            "termination_date": None,
            "pay_group_code": group["code"],
            "employment_status": "active",
            "standard_hours": 40.0,
            "annual_salary": annual_salary,
            "hourly_rate": round(annual_salary / 2080, 4),
            # Faker IBAN values are synthetic test data, never real payment instructions.
            "bank_account_token": fake.iban(),
            "tax_info_token": f"TAX-{rng.getrandbits(64):016X}",
        })

    periods = []
    for group in PAY_GROUPS:
        for month in range(1, month_count + 1):
            last_day = calendar.monthrange(year, month)[1]
            next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            payment_date = date.fromordinal(next_month.toordinal() + 4)
            periods.append({
                "pay_group_code": group["code"],
                "pay_period_code": f"PP-{year}-{month:02d}",
                "period_start": date(year, month, 1).isoformat(),
                "period_end": date(year, month, last_day).isoformat(),
                "payment_date": payment_date.isoformat(),
                "status": "open",
            })
    return {"pay_groups": groups, "employees": employees, "pay_periods": periods, "seed": seed}
