"""Backward-compatible entry point for deterministic payroll data generation.

Use `python main.py --profile starter` or `--profile full`. The implementation
is maintained in `payroll_validation.generators.generate_dataset`.
"""
from payroll_validation.generators.generate_dataset import main

if __name__ == "__main__":
    main()
