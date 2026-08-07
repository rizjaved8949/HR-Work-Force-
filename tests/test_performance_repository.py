from __future__ import annotations

from pathlib import Path

from performance.repository import PerformanceRepository


def test_repository_loads_all_720_employees(performance_data_dir: Path) -> None:
    repository = PerformanceRepository(performance_data_dir)
    summary = repository.get("performance_summary")
    assert len(summary) == 720
    assert summary["Employee_ID"].nunique() == 720


def test_repository_resolves_existing_employee(performance_data_dir: Path) -> None:
    repository = PerformanceRepository(performance_data_dir)
    employee = repository.resolve_employee(employee_id="EMP004")
    assert employee is not None
    assert employee["Employee_ID"] == "EMP004"
