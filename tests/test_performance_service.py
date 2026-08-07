from __future__ import annotations

from pathlib import Path

from performance.repository import PerformanceRepository
from performance.schemas import AnalyzePerformanceInput, PerformanceResultStatus
from performance.service import PerformanceService


def _service(data_dir: Path) -> PerformanceService:
    return PerformanceService(PerformanceRepository(data_dir))


def test_employee_evaluation_returns_score_trend_and_kpis(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="Give complete performance evaluation of EMP004")
    )
    assert result.status == PerformanceResultStatus.SUCCESS
    assert result.employee is not None
    assert result.employee["Employee_ID"] == "EMP004"
    assert any(m.metric_name == "latest_performance_score" for m in result.metrics)
    assert len(result.records) == 2


def test_employee_trend_has_12_months(performance_data_dir: Path) -> None:
    records = _service(performance_data_dir).employee_trend("EMP004", months=12)
    assert len(records) == 12


def test_employee_kpi_breakdown_weights_total_100(performance_data_dir: Path) -> None:
    rows = _service(performance_data_dir).employee_kpi_breakdown("EMP004")
    assert rows
    assert abs(sum(float(r["KPI_Weight_pct"]) for r in rows) - 100.0) < 0.01


def test_recalculation_matches_stored_score(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).recalculate_employee_month("EMP004")
    assert abs(float(result["difference_from_stored"])) <= 0.05
