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


def test_natural_language_top_departments_routes_to_ranking(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(
            question="Can you give me the performance score of top 5 departments?"
        )
    )
    assert result.status == PerformanceResultStatus.SUCCESS
    assert result.analysis_type.value == "department_ranking"
    assert len(result.records) == 5
    scores = [float(row["Average_Performance_Score"]) for row in result.records]
    assert scores == sorted(scores, reverse=True)


def test_natural_language_bottom_departments_supports_spelled_limit(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(
            question="Which are the five lowest performing departments?"
        )
    )
    assert result.analysis_type.value == "department_ranking"
    assert len(result.records) == 5
    scores = [float(row["Average_Performance_Score"]) for row in result.records]
    assert scores == sorted(scores)


def test_compare_named_departments_returns_only_requested_departments(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="Compare HR and Finance performance")
    )
    assert result.analysis_type.value == "department_ranking"
    assert {row["Department"] for row in result.records} == {"HR", "Finance"}


def test_top_employee_ranking_understands_department_scope(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(
            question="Give me the top 5 performer employees in HR department"
        )
    )
    assert result.analysis_type.value == "employee_ranking"
    assert len(result.records) == 5
    assert all(row["Department"] == "HR" for row in result.records)
    scores = [float(row["Final_Performance_Score"]) for row in result.records]
    assert scores == sorted(scores, reverse=True)


def test_bottom_employee_ranking_is_supported(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="Who are the bottom 3 performers in Finance?")
    )
    assert result.analysis_type.value == "employee_ranking"
    assert len(result.records) == 3
    assert all(row["Department"] == "Finance" for row in result.records)
    scores = [float(row["Final_Performance_Score"]) for row in result.records]
    assert scores == sorted(scores)


def test_distribution_understands_reworded_band_count(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="How many employees are strong in HR?")
    )
    assert result.analysis_type.value == "distribution"
    strong = next(row for row in result.records if row["performance_band"] == "Strong")
    assert int(strong["employee_count"]) >= 0


def test_employee_trend_understands_last_six_months(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="Show EMP004 performance over the last 6 months")
    )
    assert result.analysis_type.value == "employee_trend"
    assert len(result.records) == 6


def test_employee_name_can_be_resolved_from_question_text(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="What is Sonia Hassan's performance score?")
    )
    assert result.status == PerformanceResultStatus.SUCCESS
    assert result.analysis_type.value == "employee"
    assert result.employee is not None
    assert result.employee["Employee_ID"] == "EMP001"
    assert result.records == []


def test_historical_month_is_parsed_from_wording(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="Show top 3 departments in July 2026")
    )
    assert result.analysis_type.value == "department_ranking"
    assert len(result.records) == 3
    assert all(row["Performance_Month"] == "2026-07-01" for row in result.records)


def test_simple_employee_score_result_is_compact(performance_data_dir: Path) -> None:
    result = _service(performance_data_dir).analyze(
        AnalyzePerformanceInput(question="What is EMP004's performance score?")
    )
    assert result.analysis_type.value == "employee"
    assert result.records == []
    assert result.recommendations == []
    assert result.learning_history == []
    assert any(metric.metric_name == "latest_performance_score" for metric in result.metrics)
