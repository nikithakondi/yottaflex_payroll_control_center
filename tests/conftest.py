"""Shared pytest fixtures are added alongside each service implementation."""
import pytest

from payroll_validation.generators.generate_dataset import generate_dataset


@pytest.fixture
def database_copy(tmp_path):
    """Create an isolated, deterministic starter database for integration tests."""
    database_path = tmp_path / "payroll.db"
    output_dir = tmp_path / "generated"
    generate_dataset("starter", database_path=database_path, output_dir=output_dir)
    return database_path
