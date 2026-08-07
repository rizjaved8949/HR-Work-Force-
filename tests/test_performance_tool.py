from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("langchain")

from performance.repository import PerformanceRepository
from performance.service import PerformanceService
from performance.tool import run_analyze_employee_performance_tool


def test_plain_performance_tool(performance_data_dir: Path) -> None:
    service = PerformanceService(PerformanceRepository(performance_data_dir))
    result = run_analyze_employee_performance_tool(
        "What is the performance of EMP004?",
        service=service,
    )
    assert result["status"] == "success"
    assert result["employee"]["Employee_ID"] == "EMP004"
