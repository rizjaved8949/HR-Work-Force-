from __future__ import annotations

from pathlib import Path

from performance.learning_service import PerformanceLearningService
from performance.repository import PerformanceRepository


def test_learning_files_are_available(performance_data_dir: Path) -> None:
    service = PerformanceLearningService(PerformanceRepository(performance_data_dir))
    assert service.available is True


def test_all_declining_employees_have_recommendations(performance_data_dir: Path) -> None:
    repository = PerformanceRepository(performance_data_dir)
    summary = repository.get("performance_summary")
    declining = set(summary.loc[summary["Performance_Trend"] == "Declining", "Employee_ID"])
    recommendations = repository.get("development_recommendations")
    recommended = set(recommendations["Employee_ID"])
    assert declining <= recommended


def test_recommendations_are_traceable(performance_data_dir: Path) -> None:
    repository = PerformanceRepository(performance_data_dir)
    frame = repository.get("development_recommendations")
    assert frame["Recommendation_Basis"].fillna("").str.len().gt(0).all()
    assert frame["How_Course_Supports_Performance"].fillna("").str.len().gt(0).all()
