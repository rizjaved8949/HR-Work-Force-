from __future__ import annotations

from pathlib import Path

from performance.dashboard_service import PerformanceDashboardService
from performance.repository import PerformanceRepository


def _dashboard(data_dir: Path) -> PerformanceDashboardService:
    return PerformanceDashboardService(PerformanceRepository(data_dir))


def test_overview_covers_720_employees(performance_data_dir: Path) -> None:
    overview = _dashboard(performance_data_dir).overview()
    assert overview["employee_count"] == 720
    assert 0 <= float(overview["average_performance_score"]) <= 100


def test_organization_trend_has_12_months(performance_data_dir: Path) -> None:
    rows = _dashboard(performance_data_dir).organization_trend(months=12)
    assert len(rows) == 12


def test_department_ranking_has_16_departments(performance_data_dir: Path) -> None:
    rows = _dashboard(performance_data_dir).department_ranking(limit=20)
    assert len(rows) == 16


def test_distribution_reconciles_to_720(performance_data_dir: Path) -> None:
    rows = _dashboard(performance_data_dir).distribution()
    assert sum(int(r["employee_count"]) for r in rows) == 720


def test_attention_contains_declining_people(performance_data_dir: Path) -> None:
    rows = _dashboard(performance_data_dir).attention(limit=100)
    assert rows
    assert all(
        r["Performance_Trend"] == "Declining"
        or float(r["Latest_Performance_Score"]) < 70
        for r in rows
    )
