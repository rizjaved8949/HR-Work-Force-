"""Deterministic Employee Performance scoring formulas.

No LLM is used here. All official scores are formula-based and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd


class PerformanceScoringError(ValueError):
    """Raised when a KPI cannot be scored safely."""


@dataclass(frozen=True)
class ScoreThresholds:
    floor: float
    target: float
    stretch: float


def _number(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PerformanceScoringError(
            f"{field_name} must be numeric; received {value!r}."
        ) from exc
    if not isfinite(number):
        raise PerformanceScoringError(
            f"{field_name} must be finite; received {value!r}."
        )
    return number


def normalize_higher_better(
    actual: float,
    floor: float,
    target: float,
    stretch: float,
) -> float:
    """Normalize a higher-is-better KPI to the official 0-100 scale.

    Floor maps to 60, target to 85, stretch to 100. Values below the
    floor decline proportionally toward zero when the floor is positive.
    """

    x = _number(actual, "actual")
    f = _number(floor, "floor")
    t = _number(target, "target")
    s = _number(stretch, "stretch")

    if not (f < t < s):
        raise PerformanceScoringError(
            "HIGHER_BETTER requires floor < target < stretch."
        )

    if x <= f:
        if f <= 0:
            return 60.0 if x == f else 0.0
        return round(max(0.0, 60.0 * (x / f)), 4)
    if x <= t:
        score = 60.0 + 25.0 * ((x - f) / (t - f))
        return round(score, 4)
    if x < s:
        score = 85.0 + 15.0 * ((x - t) / (s - t))
        return round(score, 4)
    return 100.0


def normalize_lower_better(
    actual: float,
    floor: float,
    target: float,
    stretch: float,
) -> float:
    """Normalize a lower-is-better KPI to the official 0-100 scale.

    For lower-is-better KPIs the threshold order is floor > target >
    stretch. Floor maps to 60, target to 85, and stretch to 100.
    Values worse than the floor fall linearly toward zero by 2*floor.
    """

    x = _number(actual, "actual")
    f = _number(floor, "floor")
    t = _number(target, "target")
    s = _number(stretch, "stretch")

    if not (f > t > s):
        raise PerformanceScoringError(
            "LOWER_BETTER requires floor > target > stretch."
        )

    if x >= f:
        scale = max(abs(f), 1.0)
        score = 60.0 - 60.0 * ((x - f) / scale)
        return round(max(0.0, score), 4)
    if x >= t:
        score = 60.0 + 25.0 * ((f - x) / (f - t))
        return round(score, 4)
    if x > s:
        score = 85.0 + 15.0 * ((t - x) / (t - s))
        return round(score, 4)
    return 100.0


def normalize_kpi_score(
    actual: float,
    floor: float,
    target: float,
    stretch: float,
    scoring_direction: str,
) -> float:
    """Normalize one KPI using its configured scoring direction."""

    direction = str(scoring_direction).strip().upper()
    if direction == "HIGHER_BETTER":
        return normalize_higher_better(actual, floor, target, stretch)
    if direction == "LOWER_BETTER":
        return normalize_lower_better(actual, floor, target, stretch)
    raise PerformanceScoringError(
        f"Unsupported scoring direction: {scoring_direction!r}."
    )


def weighted_score(normalized_score: float, weight_pct: float) -> float:
    """Return the weighted KPI contribution to the final score."""

    score = _number(normalized_score, "normalized_score")
    weight = _number(weight_pct, "weight_pct")
    if not 0 <= score <= 100:
        raise PerformanceScoringError("normalized_score must be 0-100.")
    if not 0 <= weight <= 100:
        raise PerformanceScoringError("weight_pct must be 0-100.")
    return round(score * (weight / 100.0), 4)


def performance_band(score: float) -> str:
    """Convert a 0-100 score to the approved performance band."""

    value = _number(score, "score")
    if not 0 <= value <= 100:
        raise PerformanceScoringError("score must be 0-100.")
    if value >= 90:
        return "Exceptional"
    if value >= 80:
        return "Strong"
    if value >= 70:
        return "Meets Expectations"
    if value >= 60:
        return "Partially Meets Expectations"
    return "Improvement Required"


def calculate_monthly_score(evidence: pd.DataFrame) -> dict[str, object]:
    """Recalculate one employee-month from KPI evidence.

    The function deliberately recalculates the normalized and weighted values
    from actual/floor/target/stretch rather than trusting stored score columns.
    """

    if evidence.empty:
        raise PerformanceScoringError("No KPI evidence was supplied.")

    required_columns = {
        "Actual_KPI_Value",
        "Floor_Value",
        "Target_Value",
        "Stretch_Value",
        "Scoring_Direction",
        "KPI_Weight_pct",
    }
    missing = sorted(required_columns - set(evidence.columns))
    if missing:
        raise PerformanceScoringError(
            "Missing KPI evidence columns: " + ", ".join(missing)
        )

    total_weight = float(evidence["KPI_Weight_pct"].astype(float).sum())
    if abs(total_weight - 100.0) > 0.01:
        raise PerformanceScoringError(
            f"KPI weights must total 100%; received {total_weight:.4f}%."
        )

    normalized_scores: list[float] = []
    weighted_scores: list[float] = []

    for row in evidence.to_dict(orient="records"):
        normalized = normalize_kpi_score(
            row["Actual_KPI_Value"],
            row["Floor_Value"],
            row["Target_Value"],
            row["Stretch_Value"],
            row["Scoring_Direction"],
        )
        contribution = weighted_score(
            normalized,
            row["KPI_Weight_pct"],
        )
        normalized_scores.append(normalized)
        weighted_scores.append(contribution)

    final_score = round(sum(weighted_scores), 2)
    evidence_quality = (
        round(float(evidence["Evidence_Quality_Score"].astype(float).mean()), 4)
        if "Evidence_Quality_Score" in evidence.columns
        else None
    )

    return {
        "kpi_count": len(evidence),
        "total_weight_pct": round(total_weight, 2),
        "normalized_scores": normalized_scores,
        "weighted_scores": weighted_scores,
        "final_performance_score": final_score,
        "performance_band": performance_band(final_score),
        "average_evidence_quality": evidence_quality,
    }
