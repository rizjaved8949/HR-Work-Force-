from __future__ import annotations

import pandas as pd
import pytest

from performance.scoring import (
    calculate_monthly_score,
    normalize_kpi_score,
    performance_band,
)


def test_higher_better_thresholds() -> None:
    assert normalize_kpi_score(70, 70, 100, 115, "HIGHER_BETTER") == 60.0
    assert normalize_kpi_score(100, 70, 100, 115, "HIGHER_BETTER") == 85.0
    assert normalize_kpi_score(115, 70, 100, 115, "HIGHER_BETTER") == 100.0


def test_lower_better_thresholds() -> None:
    assert normalize_kpi_score(10, 10, 5, 2, "LOWER_BETTER") == 60.0
    assert normalize_kpi_score(5, 10, 5, 2, "LOWER_BETTER") == 85.0
    assert normalize_kpi_score(2, 10, 5, 2, "LOWER_BETTER") == 100.0


def test_performance_bands() -> None:
    assert performance_band(90) == "Exceptional"
    assert performance_band(80) == "Strong"
    assert performance_band(70) == "Meets Expectations"
    assert performance_band(60) == "Partially Meets Expectations"
    assert performance_band(59.99) == "Improvement Required"


def test_monthly_score_requires_100_percent_weights() -> None:
    frame = pd.DataFrame([
        {
            "Actual_KPI_Value": 90,
            "Floor_Value": 70,
            "Target_Value": 85,
            "Stretch_Value": 95,
            "Scoring_Direction": "HIGHER_BETTER",
            "KPI_Weight_pct": 50,
        }
    ])
    with pytest.raises(ValueError):
        calculate_monthly_score(frame)
